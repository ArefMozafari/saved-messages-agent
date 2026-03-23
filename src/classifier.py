"""AI classifier — uses Google Gemini to categorize Telegram messages."""

import json
import logging
from pathlib import Path

from google import genai
from google.genai import types

from src.config import Settings
from src.models import CategorySuggestion, ClassificationResult, MessagePayload, MessageType

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────

_SYSTEM_PROMPT_TEMPLATE = """\
You are a personal-message classifier. The user saves various items to their \
Telegram "Saved Messages" as a quick scratchpad. Your job is to analyse each \
item and suggest the best-matching categories.

Available categories (slug → description):
{category_list}

Instructions:
1. Read the content carefully.  It may be a URL, plain text, a file name, \
   a screenshot description, voice transcription, or a mix.
2. Return a JSON object with EXACTLY this schema — no extra keys, no markdown \
   fences, just raw JSON:
   {{
     "summary": "<one-line human-readable summary of the content>",
     "suggestions": [
       {{"category": "<slug>", "confidence": <0.0-1.0>, "reason": "<short reason>"}},
       ...
     ]
   }}
3. Return 1-4 suggestions, ordered by confidence descending.
4. Always include at least one suggestion.
5. If nothing matches well, use "other".
6. For images/screenshots: I will describe what the image shows — use that \
   description to classify.
"""


def _build_system_prompt(settings: Settings) -> str:
    lines = []
    for cat in settings.categories:
        lines.append(f"  {cat['slug']:16s} — {cat['emoji']} {cat['label']}: {cat['description']}")
    return _SYSTEM_PROMPT_TEMPLATE.format(category_list="\n".join(lines))


class Classifier:
    """Wraps the Gemini API for message classification."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = genai.Client(api_key=settings.gemini_api_key)
        self._system_prompt = _build_system_prompt(settings)
        self._model = "gemini-2.0-flash"

    # ── public API ────────────────────────────────────────────────────

    async def classify(self, payload: MessagePayload) -> ClassificationResult:
        """Classify a message and return category suggestions."""
        try:
            return await self._classify_impl(payload)
        except Exception:
            logger.exception("Classification failed — falling back to 'other'")
            return ClassificationResult(
                payload=payload,
                suggestions=[CategorySuggestion(category="other", confidence=1.0, reason="Classification failed")],
                ai_summary="Could not classify this message.",
            )

    # ── internals ─────────────────────────────────────────────────────

    async def _classify_impl(self, payload: MessagePayload) -> ClassificationResult:
        parts: list["types.Part"] = []

        # If there's a downloaded image/media, include it for vision
        if payload.file_path and payload.message_type in (
            MessageType.PHOTO,
            MessageType.STICKER,
            MessageType.VIDEO,
        ):
            file_path = Path(payload.file_path)
            if file_path.exists():
                mime = payload.mime_type or "image/jpeg"
                file_bytes = file_path.read_bytes()
                parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime))
                parts.append(types.Part.from_text(
                    text="Above is the media. Here is the metadata:\n" + payload.content_for_ai,
                ))
            else:
                parts.append(types.Part.from_text(text=payload.content_for_ai))
        else:
            parts.append(types.Part.from_text(text=payload.content_for_ai))

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=types.Content(role="user", parts=parts),
            config=types.GenerateContentConfig(
                system_instruction=self._system_prompt,
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )

        raw = response.text.strip()
        data = json.loads(raw)

        suggestions = []
        for s in data.get("suggestions", []):
            slug = s.get("category", "other")
            # Validate slug is known
            if slug not in self._settings.category_slugs():
                slug = "other"
            suggestions.append(
                CategorySuggestion(
                    category=slug,
                    confidence=float(s.get("confidence", 0.5)),
                    reason=s.get("reason", ""),
                )
            )

        if not suggestions:
            suggestions = [CategorySuggestion(category="other", confidence=1.0, reason="No suggestions")]

        return ClassificationResult(
            payload=payload,
            suggestions=suggestions,
            ai_summary=data.get("summary", ""),
        )
