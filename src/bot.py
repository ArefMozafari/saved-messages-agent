"""Telegram bot — sends inline-keyboard category buttons and handles selection."""

import logging
from typing import Callable, Awaitable

from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.config import Settings
from src.models import ClassificationResult, MessagePayload

logger = logging.getLogger(__name__)

# Callback data format:  action:msg_id:category_slug
# Max callback_data length is 64 bytes — we keep it compact.


def create_bot(bot_token: str, api_id: int, api_hash: str) -> Client:
    """Create and return the Pyrogram bot client."""
    return Client(
        name="saved_messages_bot",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
    )


class CategoryUI:
    """Manages the inline-keyboard flow for category selection."""

    def __init__(
        self,
        bot: Client,
        settings: Settings,
        on_confirmed: Callable[[int, list[str], MessagePayload, str], Awaitable[None]],
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._on_confirmed = on_confirmed
        # In-memory store: msg_id → {selected: set[slug], payload, ai_summary}
        self._pending: dict[int, dict] = {}

    # ── public API ────────────────────────────────────────────────────

    async def send_category_prompt(
        self,
        user_id: int,
        result: ClassificationResult,
    ) -> None:
        """Send the user an inline keyboard with suggested categories."""
        payload = result.payload
        msg_id = payload.message_id

        # Store context for callback handling
        self._pending[msg_id] = {
            "selected": set(),
            "payload": payload,
            "ai_summary": result.ai_summary,
            "suggestions": result.suggestions, 
        }

        # Build summary text
        summary = result.ai_summary or "(no summary)"
        strategy = result.strategy_used or "Unknown"
        text = (
            f"📥 **New Saved Message** (#{msg_id})\n\n"
            f"📝 *{summary}*\n"
            f"🧠 Classified by: {strategy}\n\n"
            f"Select a category to save:"
        )

        keyboard = self._build_keyboard(msg_id, result)
        await self._bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=keyboard,
        )

    async def handle_callback(self, _: Client, cb: CallbackQuery) -> None:
        """Handle an inline-button tap."""
        data = cb.data or ""
        parts = data.split(":", 2)
        if len(parts) < 3:
            await cb.answer("Invalid button data")
            return

        action, msg_id_str, slug = parts
        try:
            msg_id = int(msg_id_str)
        except ValueError:
            await cb.answer("Invalid message ID")
            return

        pending = self._pending.get(msg_id)
        if not pending:
            await cb.answer("⏳ This selection has expired.")
            return

        if action == "tog":
            # Toggle category
            selected: set = pending["selected"]
            if slug in selected:
                selected.discard(slug)
            else:
                selected.add(slug)
            # Rebuild keyboard
            keyboard = self._build_selection_keyboard(msg_id, selected, pending.get("suggestions", []))
            await cb.message.edit_reply_markup(reply_markup=keyboard)
            cat = self._settings.category_by_slug(slug)
            label = cat["label"] if cat else slug
            state = "✅" if slug in selected else "⬜"
            await cb.answer(f"{state} {label}")

        elif action == "ok":
            # Confirm selection
            selected = pending["selected"]
            if not selected:
                await cb.answer("Please select at least one category!", show_alert=True)
                return

            # Call the confirmation handler
            await self._on_confirmed(
                msg_id,
                list(selected),
                pending["payload"],
                pending["ai_summary"],
            )

            # Update the message
            cat_labels = []
            for s in selected:
                cat = self._settings.category_by_slug(s)
                if cat:
                    cat_labels.append(f"{cat['emoji']} {cat['label']}")
                elif s.startswith("new_"):
                    cat_labels.append(f"✨ {s[4:].title()}")
                else:
                    cat_labels.append(s)

            await cb.message.edit_text(
                f"✅ **Saved to Notion!**\n\n"
                f"Categories: {', '.join(cat_labels)}\n"
                f"Message #{msg_id}"
            )
            # Clean up
            self._pending.pop(msg_id, None)
            await cb.answer("Saved! ✅")

        elif action == "skip":
            self._pending.pop(msg_id, None)
            await cb.message.edit_text(f"⏭️ Skipped message #{msg_id}")
            await cb.answer("Skipped")

    # ── keyboard builders ─────────────────────────────────────────────

    def _build_keyboard(
        self,
        msg_id: int,
        result: ClassificationResult,
    ) -> InlineKeyboardMarkup:
        """Build initial keyboard with AI-suggested categories highlighted."""
        rows: list[list[InlineKeyboardButton]] = []
        suggested_slugs = {s.category for s in result.suggestions}

        # Suggested categories first (2 per row)
        row: list[InlineKeyboardButton] = []
        for suggestion in result.suggestions:
            cat = self._settings.category_by_slug(suggestion.category)
            
            if not cat:
                if suggestion.category.startswith("new_"):
                    # Dynamic category creation!
                    cat = {"slug": suggestion.category, "emoji": "✨", "label": f"New: {suggestion.category[4:].title()}"}
                else:
                    continue
                    
            label = f"⭐ {cat['emoji']} {cat['label']}"
            row.append(InlineKeyboardButton(
                text=label,
                callback_data=f"tog:{msg_id}:{cat['slug']}",
            ))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        # Remaining categories (2 per row)
        row = []
        for cat in self._settings.categories:
            if cat["slug"] in suggested_slugs:
                continue
            label = f"{cat['emoji']} {cat['label']}"
            row.append(InlineKeyboardButton(
                text=label,
                callback_data=f"tog:{msg_id}:{cat['slug']}",
            ))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        # Confirm + Skip
        rows.append([
            InlineKeyboardButton(text="✅ Confirm", callback_data=f"ok:{msg_id}:_"),
            InlineKeyboardButton(text="⏭️ Skip", callback_data=f"skip:{msg_id}:_"),
        ])

        return InlineKeyboardMarkup(rows)

    def _build_selection_keyboard(
        self,
        msg_id: int,
        selected: set[str],
        suggestions: list,
    ) -> InlineKeyboardMarkup:
        """Rebuild keyboard reflecting current selection state, protecting dynamic models."""
        rows: list[list[InlineKeyboardButton]] = []
        row: list[InlineKeyboardButton] = []

        # Gather standard options and inject any dynamic ones that were offered
        all_options = list(self._settings.categories)
        dynamic_slugs = {c["slug"] for c in all_options}

        for suggestion in suggestions:
            slug = suggestion.category
            if slug not in dynamic_slugs and slug.startswith("new_"):
                all_options.insert(0, {"slug": slug, "emoji": "✨", "label": f"New: {slug[4:].title()}"})
                dynamic_slugs.add(slug)

        for cat in all_options:
            check = "✅" if cat["slug"] in selected else "⬜"
            label = f"{check} {cat['emoji']} {cat['label']}"
            row.append(InlineKeyboardButton(
                text=label,
                callback_data=f"tog:{msg_id}:{cat['slug']}",
            ))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        rows.append([
            InlineKeyboardButton(text="✅ Confirm", callback_data=f"ok:{msg_id}:_"),
            InlineKeyboardButton(text="⏭️ Skip", callback_data=f"skip:{msg_id}:_"),
        ])

        return InlineKeyboardMarkup(rows)
