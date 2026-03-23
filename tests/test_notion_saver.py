"""Tests for the Notion saver — payload construction (no API calls)."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from src.models import MessagePayload, MessageType
from src.notion_saver import NotionSaver


def _make_payload(**kwargs) -> MessagePayload:
    defaults = dict(
        message_id=42,
        message_type=MessageType.TEXT,
        raw_text="Check this out",
        timestamp=datetime(2026, 3, 23, tzinfo=timezone.utc),
    )
    defaults.update(kwargs)
    return MessagePayload(**defaults)


class TestBuildProperties:
    """Tests for NotionSaver._build_properties static method."""

    def test_basic_properties(self):
        payload = _make_payload()
        props = NotionSaver._build_properties("Test title", payload)

        assert props["Title"]["title"][0]["text"]["content"] == "Test title"
        assert props["Source"]["rich_text"][0]["text"]["content"] == "Telegram Saved Messages"
        assert "Date Saved" in props

    def test_url_included_when_present(self):
        payload = _make_payload(url="https://example.com")
        props = NotionSaver._build_properties("Link item", payload)

        assert props["URL"]["url"] == "https://example.com"

    def test_url_absent_when_empty(self):
        payload = _make_payload(url="")
        props = NotionSaver._build_properties("No URL", payload)

        assert "URL" not in props

    def test_title_truncated_at_100(self):
        long_title = "A" * 200
        payload = _make_payload()
        props = NotionSaver._build_properties(long_title, payload)

        assert len(props["Title"]["title"][0]["text"]["content"]) == 100


class TestBuildBodyBlocks:
    """Tests for NotionSaver._build_body_blocks static method."""

    def test_summary_creates_callout(self):
        payload = _make_payload()
        blocks = NotionSaver._build_body_blocks(payload, "AI summary here")

        assert blocks[0]["type"] == "callout"
        assert "AI summary here" in blocks[0]["callout"]["rich_text"][0]["text"]["content"]

    def test_raw_text_creates_paragraph(self):
        payload = _make_payload(raw_text="Hello world")
        blocks = NotionSaver._build_body_blocks(payload, "")

        paragraph_blocks = [b for b in blocks if b["type"] == "paragraph"]
        assert len(paragraph_blocks) >= 1
        assert "Hello world" in paragraph_blocks[0]["paragraph"]["rich_text"][0]["text"]["content"]

    def test_url_creates_bookmark(self):
        payload = _make_payload(url="https://example.com")
        blocks = NotionSaver._build_body_blocks(payload, "")

        bookmark_blocks = [b for b in blocks if b["type"] == "bookmark"]
        assert len(bookmark_blocks) == 1
        assert bookmark_blocks[0]["bookmark"]["url"] == "https://example.com"

    def test_long_text_split_into_chunks(self):
        long_text = "X" * 5000
        payload = _make_payload(raw_text=long_text)
        blocks = NotionSaver._build_body_blocks(payload, "")

        paragraph_blocks = [b for b in blocks if b["type"] == "paragraph"]
        assert len(paragraph_blocks) == 3  # 5000 / 2000 = 2.5 → 3 chunks

    def test_empty_content_produces_no_paragraph(self):
        payload = _make_payload(raw_text="", caption="")
        blocks = NotionSaver._build_body_blocks(payload, "Summary only")

        paragraph_blocks = [b for b in blocks if b["type"] == "paragraph"]
        assert len(paragraph_blocks) == 0
