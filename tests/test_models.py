"""Tests for the data models."""

from __future__ import annotations

import pytest
from src.models import MessagePayload, MessageType


class TestMessagePayload:
    """Tests for MessagePayload.content_for_ai property."""

    def test_text_only(self):
        p = MessagePayload(message_id=1, message_type=MessageType.TEXT, raw_text="Hello")
        ai = p.content_for_ai
        assert "Text: Hello" in ai
        assert "Message type: text" in ai

    def test_link_with_url(self):
        p = MessagePayload(
            message_id=2,
            message_type=MessageType.LINK,
            raw_text="https://example.com",
            url="https://example.com",
        )
        ai = p.content_for_ai
        assert "URL: https://example.com" in ai

    def test_document_with_filename(self):
        p = MessagePayload(
            message_id=3,
            message_type=MessageType.DOCUMENT,
            file_name="report.pdf",
            mime_type="application/pdf",
        )
        ai = p.content_for_ai
        assert "File: report.pdf" in ai
        assert "MIME type: application/pdf" in ai

    def test_empty_message(self):
        p = MessagePayload(message_id=4, message_type=MessageType.OTHER)
        ai = p.content_for_ai
        assert "Message type: other" in ai
