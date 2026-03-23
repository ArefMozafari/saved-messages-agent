"""Configuration loader — reads .env and exposes a Settings object."""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Default categories ────────────────────────────────────────────────
DEFAULT_CATEGORIES: list[dict[str, str]] = [
    {"slug": "wishlist",    "emoji": "🛒", "label": "Wishlist",       "description": "Product links, screenshots of items to buy"},
    {"slug": "watch_later", "emoji": "📺", "label": "Watch Later",    "description": "Movie / series names, YouTube / reel links"},
    {"slug": "read_later",  "emoji": "📚", "label": "Read Later",     "description": "Book names, article links, blog posts"},
    {"slug": "educational", "emoji": "🎓", "label": "Educational",    "description": "Tutorial links, educational reels, courses"},
    {"slug": "credentials", "emoji": "🔐", "label": "Credentials",    "description": "Passwords, API keys, login info"},
    {"slug": "ideas",       "emoji": "💡", "label": "Ideas",          "description": "Thoughts, ideas to explore later"},
    {"slug": "music",       "emoji": "🎵", "label": "Music / Practice","description": "Singing practices, music files, playlists"},
    {"slug": "useful_links","emoji": "🔗", "label": "Useful Links",   "description": "General helpful links to save"},
    {"slug": "notes",       "emoji": "📝", "label": "Notes",          "description": "Quick notes, reminders, to-check-later"},
    {"slug": "other",       "emoji": "📎", "label": "Other",          "description": "Anything else"},
]


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    # Telegram userbot
    telegram_api_id: int
    telegram_api_hash: str
    # Telegram bot
    telegram_bot_token: str
    # Gemini
    gemini_api_key: str
    # Notion
    notion_token: str
    notion_parent_page_id: str
    # Misc
    log_level: str = "INFO"
    categories: list[dict[str, str]] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_api_id=int(_require("TELEGRAM_API_ID")),
            telegram_api_hash=_require("TELEGRAM_API_HASH"),
            telegram_bot_token=_require("TELEGRAM_BOT_TOKEN"),
            gemini_api_key=_require("GEMINI_API_KEY"),
            notion_token=_require("NOTION_TOKEN"),
            notion_parent_page_id=_require("NOTION_PARENT_PAGE_ID"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    def category_by_slug(self, slug: str) -> Optional[dict[str, str]]:
        return next((c for c in self.categories if c["slug"] == slug), None)

    def category_slugs(self) -> list[str]:
        return [c["slug"] for c in self.categories]
