"""AI classifier — uses multiple LLMs to categorize Telegram messages."""

import json
import logging
import re
from pathlib import Path

import httpx
from google import genai
from google.genai import types

from src.config import Settings
from src.models import CategorySuggestion, ClassificationResult, MessagePayload, MessageType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_TEMPLATE = """\
You are a personal-message classifier. The user saves various items to their \
Telegram "Saved Messages" as a quick scratchpad. Your job is to analyse each \
item and suggest the best-matching categories.

Available categories (slug -> description):
{category_list}

Instructions:
1. Read the content carefully. It may be a URL, plain text, a file name, \
   a screenshot description, or a mix.
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
5. If nothing matches well, you MUST suggest a NEW category. \
   Format the slug starting with "new_" (e.g., "new_recipes", "new_fitness"). \
   This tells the system you are suggesting a brand new category.
"""

def _build_system_prompt(settings: Settings) -> str:
    lines = []
    for cat in settings.categories:
        lines.append(f"  {cat['slug']:16s} — {cat['emoji']} {cat['label']}: {cat['description']}")
    return _SYSTEM_PROMPT_TEMPLATE.format(category_list="\n".join(lines))


class Classifier:
    """Wraps multiple APIs for message classification with fallback."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._system_prompt = _build_system_prompt(settings)
        # Timeout for httpx
        self._timeout_seconds = 15.0

    async def classify(self, payload: MessagePayload) -> ClassificationResult:
        """Classify a message by daisy-chaining available providers."""
        
        retry_delay_found = None
        
        # 1. Google Gemini (Internal Fallbacks)
        if self._settings.gemini_api_key:
            gemini_models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]
            for model_name in gemini_models:
                try:
                    data = await self._classify_gemini(payload, model_name)
                    return self._build_result(payload, data, f"Google Gemini ({model_name})")
                except Exception as e:
                    err_str = str(e)
                    if "retryDelay" in err_str:
                        match = re.search(r"'retryDelay':\s*'([^']+)'", err_str)
                        if match:
                            retry_delay_found = match.group(1)
                            logger.warning("⚠️  Gemini (%s) exhausted (Resets in %s). Skipping...", model_name, retry_delay_found)
                    else:
                        logger.warning("⚠️  Gemini (%s) unavailable. Skipping...", model_name)

        # 2. xAI Grok
        if self._settings.xai_api_key:
            try:
                data = await self._classify_openai_compatible(
                    payload, self._settings.xai_api_key, "grok-beta", "https://api.x.ai/v1/chat/completions"
                )
                return self._build_result(payload, data, "xAI Grok")
            except Exception:
                logger.warning("⚠️  xAI Grok unavailable. Skipping...")

        # 3. OpenAI ChatGPT
        if self._settings.openai_api_key:
            try:
                data = await self._classify_openai_compatible(
                    payload, self._settings.openai_api_key, "gpt-4o-mini", "https://api.openai.com/v1/chat/completions"
                )
                return self._build_result(payload, data, "OpenAI ChatGPT")
            except Exception:
                logger.warning("⚠️  OpenAI unavailable. Skipping...")

        # 4. Anthropic Claude
        if self._settings.anthropic_api_key:
            try:
                data = await self._classify_anthropic(payload)
                return self._build_result(payload, data, "Anthropic Claude")
            except Exception:
                logger.warning("⚠️  Anthropic unavailable. Skipping...")

        # 5. Local Ollama
        if self._settings.ollama_host:
            try:
                url = self._settings.ollama_host.rstrip('/')
                if not url.endswith("/api/chat") and not url.endswith("/v1/chat/completions"):
                    url = f"{url}/v1/chat/completions"
                data = await self._classify_openai_compatible(
                    payload, "ollama", "llama3.2", url
                )
                return self._build_result(payload, data, "Local Ollama")
            except Exception:
                logger.warning("⚠️  Local Ollama unavailable. Skipping...")

        # 6. Regex / Keyword Fallback
        logger.warning("⚠️  All AI providers failed. Using Regex Fallback.")
        data = self._classify_regex(payload)
        
        if retry_delay_found:
            data["summary"] += f" (Note: Gemini quota resets in {retry_delay_found})"
            
        return self._build_result(payload, data, "Regex Fallback")


    def _build_result(self, payload: MessagePayload, data: dict, strategy: str) -> ClassificationResult:
        suggestions = []
        for s in data.get("suggestions", []):
            slug = s.get("category", "other")
            # If not in settings, ensure it's prefixed with "new_" so we know it's dynamic
            if slug not in self._settings.category_slugs() and not slug.startswith("new_"):
                slug = "other"
                
            suggestions.append(
                CategorySuggestion(
                    category=slug,
                    confidence=float(s.get("confidence", 0.5)),
                    reason=s.get("reason", ""),
                )
            )

        if not suggestions:
            suggestions = [CategorySuggestion(category="other", confidence=1.0, reason="Fallback")]

        return ClassificationResult(
            payload=payload,
            suggestions=suggestions,
            strategy_used=strategy,
            ai_summary=data.get("summary", "Classified natively without AI details."),
        )

    # ── Implementations ───────────────────────────────────────────────

    async def _classify_gemini(self, payload: MessagePayload, model_name: str) -> dict:
        client = genai.Client(api_key=self._settings.gemini_api_key)
        parts = []
        if payload.file_path and payload.message_type in (MessageType.PHOTO, MessageType.STICKER, MessageType.VIDEO):
            file_path = Path(payload.file_path)
            if file_path.exists():
                mime = payload.mime_type or "image/jpeg"
                parts.append(types.Part.from_bytes(data=file_path.read_bytes(), mime_type=mime))
        
        parts.append(types.Part.from_text(text=payload.content_for_ai))

        response = await client.aio.models.generate_content(
            model=model_name,
            contents=types.Content(role="user", parts=parts),
            config=types.GenerateContentConfig(
                system_instruction=self._system_prompt,
                temperature=0.3,
                response_mime_type="application/json",
            ),
        )
        return self._parse_json(response.text)

    async def _classify_openai_compatible(self, payload: MessagePayload, api_key: str, model: str, url: str) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user", "content": payload.content_for_ai}
                    ],
                    "temperature": 0.3
                }
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return self._parse_json(content)

    async def _classify_anthropic(self, payload: MessagePayload) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._settings.anthropic_api_key, 
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "system": self._system_prompt,
                    "messages": [{"role": "user", "content": payload.content_for_ai}],
                    "max_tokens": 1024,
                    "temperature": 0.3
                }
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["content"][0]["text"]
            return self._parse_json(content)

    def _classify_regex(self, payload: MessagePayload) -> dict:
        text = payload.raw_text.lower() + " " + payload.caption.lower()
        slug = "other"
        
        if "http" in text or "www." in text:
            if "youtube.com" in text or "youtu.be" in text or "vimeo" in text or "instagram.com/reel" in text:
                slug = "watch_later"
            elif "github.com" in text or "stackoverflow.com" in text or "tutorial" in text:
                slug = "educational"
            else:
                slug = "read_later"
        elif "password" in text or "api_key" in text or "login" in text:
            slug = "credentials"
        elif "idea:" in text or "ideas" in text or "thought:" in text:
            slug = "ideas"
        elif "buy" in text or "price" in text or "shop" in text or "amazon." in text:
            slug = "wishlist"
            
        return {
            "summary": payload.content_for_ai[:50] + "...",
            "suggestions": [{"category": slug, "confidence": 1.0, "reason": "Keyword matched (Regex Fallback)"}]
        }

    def _parse_json(self, raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```json"):
            raw = raw[7:]
        elif raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return json.loads(raw.strip())
