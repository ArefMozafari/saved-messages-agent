"""Telegram userbot — monitors Saved Messages via Pyrogram."""

import logging
import re
import tempfile
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import MessageMediaType

from src.models import MessagePayload, MessageType

logger = logging.getLogger(__name__)

# ── URL extraction regex ──────────────────────────────────────────────
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# ── Media type mapping ────────────────────────────────────────────────
_MEDIA_MAP: dict[MessageMediaType | None, MessageType] = {
    MessageMediaType.PHOTO: MessageType.PHOTO,
    MessageMediaType.VIDEO: MessageType.VIDEO,
    MessageMediaType.VOICE: MessageType.VOICE,
    MessageMediaType.AUDIO: MessageType.AUDIO,
    MessageMediaType.DOCUMENT: MessageType.DOCUMENT,
    MessageMediaType.STICKER: MessageType.STICKER,
    MessageMediaType.ANIMATION: MessageType.ANIMATION,
    None: MessageType.TEXT,
}


def _detect_type(msg: Message) -> MessageType:
    return _MEDIA_MAP.get(msg.media, MessageType.OTHER)


def _extract_url(text: str) -> str:
    """Pull the first URL from *text*, or return ''."""
    match = _URL_RE.search(text or "")
    return match.group(0) if match else ""


async def _download_media(msg: Message) -> tuple[str, str]:
    """Download media to a temp file. Returns (path, mime_type)."""
    try:
        tmp_dir = Path(tempfile.gettempdir()) / "saved_msg_agent"
        tmp_dir.mkdir(exist_ok=True)
        path = await msg.download(file_name=str(tmp_dir / f"{msg.id}"))
        if path:
            # Derive a rough MIME from the file extension
            ext = Path(path).suffix.lower()
            mime_map = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                ".webp": "image/webp", ".gif": "image/gif", ".mp4": "video/mp4",
                ".ogg": "audio/ogg", ".oga": "audio/ogg", ".mp3": "audio/mpeg",
                ".m4a": "audio/mp4", ".pdf": "application/pdf",
            }
            mime = mime_map.get(ext, "application/octet-stream")
            return str(path), mime
    except Exception:
        logger.exception("Failed to download media for message %s", msg.id)
    return "", ""


async def extract_payload(msg: Message) -> MessagePayload:
    """Convert a Pyrogram Message into a MessagePayload."""
    msg_type = _detect_type(msg)
    raw_text = msg.text or ""
    caption = msg.caption or ""
    combined = f"{raw_text} {caption}".strip()
    url = _extract_url(combined)

    # If the message is purely a URL, mark it as LINK type
    if url and msg_type == MessageType.TEXT and raw_text.strip() == url:
        msg_type = MessageType.LINK

    file_path = ""
    mime_type = ""
    file_name = ""

    # Download media if present
    if msg.media:
        file_path, mime_type = await _download_media(msg)
        # Try to get a file name
        if msg.document:
            file_name = msg.document.file_name or ""
        elif msg.audio:
            file_name = msg.audio.file_name or ""
        elif msg.video:
            file_name = msg.video.file_name or ""

    return MessagePayload(
        message_id=msg.id,
        message_type=msg_type,
        raw_text=raw_text,
        caption=caption,
        url=url,
        file_name=file_name,
        file_path=file_path,
        mime_type=mime_type,
    )


def create_userbot(api_id: int, api_hash: str) -> Client:
    """Create and return the Pyrogram userbot client."""
    return Client(
        name="saved_messages_userbot",
        api_id=api_id,
        api_hash=api_hash,
    )
