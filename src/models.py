"""Shared data models used across modules."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MessageType(Enum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    VOICE = "voice"
    AUDIO = "audio"
    DOCUMENT = "document"
    STICKER = "sticker"
    ANIMATION = "animation"
    LINK = "link"
    OTHER = "other"


@dataclass
class MessagePayload:
    """Normalized representation of a Telegram Saved Message."""

    message_id: int
    message_type: MessageType
    raw_text: str = ""
    caption: str = ""
    url: str = ""
    file_name: str = ""
    file_path: str = ""          # local temp path after download
    mime_type: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def content_for_ai(self) -> str:
        """Build the text blob that will be sent to the AI classifier."""
        parts: list[str] = []
        if self.raw_text:
            parts.append(f"Text: {self.raw_text}")
        if self.caption:
            parts.append(f"Caption: {self.caption}")
        if self.url:
            parts.append(f"URL: {self.url}")
        if self.file_name:
            parts.append(f"File: {self.file_name}")
        if self.mime_type:
            parts.append(f"MIME type: {self.mime_type}")
        parts.append(f"Message type: {self.message_type.value}")
        return "\n".join(parts) if parts else "Empty message"


@dataclass
class CategorySuggestion:
    """A single AI-suggested category for a message."""

    category: str       # slug
    confidence: float   # 0.0 – 1.0
    reason: str = ""


@dataclass
class ClassificationResult:
    """Full classification output from the AI."""

    payload: MessagePayload
    suggestions: list[CategorySuggestion]
    ai_summary: str = ""    # short human-readable summary of the content
