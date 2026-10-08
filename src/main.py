"""Main orchestrator — wires userbot, classifier, bot, and Notion saver."""

import asyncio
import logging
from typing import Optional

from pyrogram import Client, filters, compose
from pyrogram.types import Message

from src.config import Settings
from src.userbot import create_userbot, extract_payload
from src.bot import create_bot, CategoryUI
from src.classifier import Classifier
from src.notion_saver import NotionSaver
from src.models import MessagePayload

logger = logging.getLogger(__name__)


class Agent:
    """Coordinates the full Saved-Messages → AI → Buttons → Notion pipeline."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._classifier = Classifier(settings)
        self._notion = NotionSaver(settings)
        self._user_id: Optional[int] = None  # resolved at startup
        # We must initialize clients inside an async method so they bind to the correct event loop
        self._userbot: Optional[Client] = None
        self._bot: Optional[Client] = None
        self._ui: Optional[CategoryUI] = None
        
        # Queue for throttling API requests
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None

    # ── lifecycle ─────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the agent and run both clients."""
        logging.basicConfig(
            level=getattr(logging, self._settings.log_level, logging.INFO),
            format="%(asctime)s │ %(name)-28s │ %(levelname)-5s │ %(message)s",
            datefmt="%H:%M:%S",
        )

        logger.info("🚀 Starting Saved Messages Agent…")

        # Silence noisy third-party dependencies
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("google_genai").setLevel(logging.WARNING)
        logging.getLogger("pyrogram").setLevel(logging.WARNING)

        # Initialize clients in the running asyncio loop
        self._userbot = create_userbot(self._settings.telegram_api_id, self._settings.telegram_api_hash)
        self._bot = create_bot(self._settings.telegram_bot_token, self._settings.telegram_api_id, self._settings.telegram_api_hash)
        self._ui = CategoryUI(self._bot, self._settings, on_confirmed=self._on_category_confirmed)

        # Initialize Notion databases
        await self._notion.setup()
        logger.info("✅ Notion databases ready")

        # Register handlers
        self._register_handlers()

        # Explicitly start clients to avoid compose() loop issues
        await self._userbot.start()
        await self._bot.start()
        
        # Start the background worker for processing messages sequentially
        self._worker_task = asyncio.create_task(self._process_queue())

        # Keep running
        import pyrogram
        await pyrogram.idle()

        # Shutdown gracefully
        if self._worker_task:
            self._worker_task.cancel()
        await self._userbot.stop()
        await self._bot.stop()

    # ── handler registration ──────────────────────────────────────────

    def _register_handlers(self) -> None:
        """Wire up Pyrogram message/callback handlers."""

        @self._userbot.on_message(filters.chat("me") & ~filters.outgoing & filters.incoming)
        async def on_saved_message(_: Client, msg: Message) -> None:
            await self._handle_saved_message(msg)

        # Also handle messages that the user sends TO themselves (forwards, etc.)
        @self._userbot.on_message(filters.chat("me") & filters.outgoing)
        async def on_self_message(_: Client, msg: Message) -> None:
            await self._handle_saved_message(msg)

        @self._bot.on_callback_query()
        async def on_callback(client: Client, cb) -> None:
            await self._ui.handle_callback(client, cb)

        @self._bot.on_message(filters.command("start"))
        async def on_start(_: Client, msg: Message) -> None:
            await msg.reply(
                "👋 **Saved Messages Agent**\n\n"
                "I'll watch your Saved Messages and help you categorize them into Notion.\n\n"
                "Just save a message in Telegram and I'll send you category options here!",
            )

        @self._bot.on_message(filters.command("categories"))
        async def on_categories(_: Client, msg: Message) -> None:
            lines: list[str] = []
            for cat in self._settings.categories:
                lines.append(f"  {cat['emoji']} **{cat['label']}** — {cat['description']}")
            await msg.reply("📋 **Categories:**\n\n" + "\n".join(lines))

    # ── pipeline ──────────────────────────────────────────────────────

    async def _handle_saved_message(self, msg: Message) -> None:
        """Enqueue a newly saved message for processing."""
        await self._message_queue.put(msg)
        logger.info("Enqueued message #%s (Queue size: %s)", msg.id, self._message_queue.qsize())

    async def _process_queue(self) -> None:
        """Background worker that sequentially processes messages from the queue to respect rate limits."""
        while True:
            try:
                msg = await self._message_queue.get()
                await self._process_single_message(msg)
                self._message_queue.task_done()
                
                # Throttle processing to prevent 429 API Rate Limits 
                # Gemini free tier allows ~15 requests per minute. 
                # A 7 second delay ensures we never exceed 8 requests a min.
                await asyncio.sleep(7)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Queue processor crashed: %s", repr(e))
                await asyncio.sleep(7)

    async def _process_single_message(self, msg: Message) -> None:
        """Process a single message through the full pipeline."""
        try:
            logger.info("📩 Processing saved message #%s (type: %s)", msg.id, msg.media or "text")

            # 1. Extract payload
            payload = await extract_payload(msg)

            # 2. Resolve user ID (needed to send bot messages)
            if self._user_id is None:
                me = await self._userbot.get_me()
                self._user_id = me.id

            # 3. Classify with AI
            result = await self._classifier.classify(payload)
            logger.info(
                "🤖 [%s] Classified #%s → %s",
                result.strategy_used,
                msg.id,
                [s.category for s in result.suggestions],
            )

            # 4. Send category buttons via bot
            await self._ui.send_category_prompt(self._user_id, result)

        except Exception:
            logger.exception("Failed to process saved message #%s", msg.id)

    async def _on_category_confirmed(
        self,
        msg_id: int,
        categories: list[str],
        payload: MessagePayload,
        ai_summary: str,
    ) -> None:
        """Called when the user confirms their category selection."""
        for cat_slug in categories:
            try:
                url = await self._notion.save_item(cat_slug, payload, ai_summary)
                logger.info("📝 Saved #%s to Notion [%s]: %s", msg_id, cat_slug, url)
            except Exception:
                logger.exception("Failed to save #%s to Notion [%s]", msg_id, cat_slug)
