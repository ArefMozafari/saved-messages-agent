"""Notion integration — auto-creates category databases and saves items."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from notion_client import AsyncClient

from src.config import Settings
from src.models import MessagePayload

logger = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent / "notion_db_cache.json"

# Maximum Notion rich-text block length (API limit is 2000 chars)
_MAX_TEXT_LEN = 2000


class NotionSaver:
    """Creates category databases in Notion and saves classified items."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncClient(auth=settings.notion_token)
        self._parent_page_id = settings.notion_parent_page_id
        self._db_cache: dict[str, str] = {}  # slug -> database_id

    # ── lifecycle ─────────────────────────────────────────────────────

    async def setup(self) -> None:
        """Load the DB-ID cache or create missing databases."""
        self._load_cache()
        await self._ensure_databases()

    # ── public API ────────────────────────────────────────────────────

    async def save_item(
        self,
        category_slug: str,
        payload: MessagePayload,
        ai_summary: str,
    ) -> str:
        """Save an item to the Notion database for *category_slug*.

        Returns the URL of the created Notion page.
        """
        db_id = self._db_cache.get(category_slug)
        if db_id:
            try:
                db = await self._client.databases.retrieve(db_id)
                if db.get("archived") or db.get("in_trash"):
                    raise ValueError("Database is trashed")
            except Exception:
                logger.warning("Cached DB for %s is invalid or trashed in Notion. Recreating...", category_slug)
                self._db_cache.pop(category_slug, None)
                db_id = None

        if not db_id:
            await self._ensure_databases()
            db_id = self._db_cache.get(category_slug)

        if not db_id:
            logger.warning("No DB for category %s — falling back to 'other'", category_slug)
            db_id = self._db_cache.get("other")
            if not db_id:
                raise RuntimeError("'other' database not found in cache")

        title = ai_summary[:100] if ai_summary else "Saved item"
        properties = self._build_properties(title, payload)
        children = self._build_body_blocks(payload, ai_summary)

        page = await self._client.pages.create(
            parent={"database_id": db_id},
            properties=properties,
            children=children,
        )

        page_url = page.get("url", "")
        logger.info("Saved to Notion: %s → %s", category_slug, page_url)
        return page_url

    # ── database management ───────────────────────────────────────────

    async def _ensure_databases(self) -> None:
        """Create any missing category databases under the parent page."""
        changed = False
        for cat in self._settings.categories:
            slug = cat["slug"]
            if slug in self._db_cache:
                continue

            logger.info("Creating Notion database for category: %s", cat["label"])
            db = await self._client.databases.create(
                parent={"type": "page_id", "page_id": self._parent_page_id},
                title=[{"type": "text", "text": {"content": f"{cat['emoji']} {cat['label']}"}}],
                properties={
                    "Title": {"title": {}},
                    "Source": {
                        "rich_text": {},
                    },
                    "URL": {"url": {}},
                    "Date Saved": {"date": {}},
                    "Tags": {"multi_select": {"options": []}},
                },
            )
            self._db_cache[slug] = db["id"]
            changed = True

        if changed:
            self._save_cache()

    # ── page construction ─────────────────────────────────────────────

    @staticmethod
    def _build_properties(title: str, payload: MessagePayload) -> dict:  # type: ignore[type-arg]
        props: dict = {
            "title": {"title": [{"text": {"content": title[:100]}}]},
        }
        return props

    @staticmethod
    def _build_body_blocks(payload: MessagePayload, ai_summary: str) -> list[dict]:  # type: ignore[type-arg]
        blocks: list[dict] = []
        
        # Add metadata as blocks at the top
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        meta_text = f"📅 Saved: {date_str}\n📥 Source: Telegram Saved Messages"
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": [{"text": {"content": meta_text}}]}
        })
        blocks.append({"object": "block", "type": "divider", "divider": {}})

        if ai_summary:
            blocks.append({
                "object": "block",
                "type": "callout",
                "callout": {
                    "icon": {"type": "emoji", "emoji": "🤖"},
                    "rich_text": [{"type": "text", "text": {"content": ai_summary[:_MAX_TEXT_LEN]}}],
                },
            })

        raw = payload.raw_text or payload.caption or ""
        if raw:
            # Split into chunks for Notion's 2000-char limit
            for i in range(0, len(raw), _MAX_TEXT_LEN):
                chunk = raw[i : i + _MAX_TEXT_LEN]
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}],
                    },
                })

        if payload.url:
            blocks.append({
                "object": "block",
                "type": "bookmark",
                "bookmark": {"url": payload.url},
            })

        return blocks

    # ── cache I/O ─────────────────────────────────────────────────────

    def _load_cache(self) -> None:
        if _CACHE_PATH.exists():
            try:
                self._db_cache = json.loads(_CACHE_PATH.read_text())
                logger.info("Loaded Notion DB cache with %d entries", len(self._db_cache))
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt DB cache — will recreate")
                self._db_cache = {}

    def _save_cache(self) -> None:
        _CACHE_PATH.write_text(json.dumps(self._db_cache, indent=2))
        logger.info("Saved Notion DB cache → %s", _CACHE_PATH)
