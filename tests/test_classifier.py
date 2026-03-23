"""Tests for the AI classifier module."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.classifier import Classifier
from src.config import Settings, DEFAULT_CATEGORIES
from src.models import MessagePayload, MessageType, CategorySuggestion


def _make_settings() -> Settings:
    return Settings(
        telegram_api_id=12345,
        telegram_api_hash="fake_hash",
        telegram_bot_token="fake:token",
        gemini_api_key="fake_key",
        notion_token="fake_notion",
        notion_parent_page_id="fake_page",
    )


def _make_payload(**kwargs) -> MessagePayload:
    defaults = dict(message_id=1, message_type=MessageType.TEXT)
    defaults.update(kwargs)
    return MessagePayload(**defaults)


def _mock_gemini_response(data: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(data)
    return mock_resp


class TestClassifier:
    """Unit tests for the Classifier class."""

    @pytest.mark.asyncio
    async def test_product_url_classified_as_wishlist(self):
        """A product URL should be classified as 'wishlist'."""
        settings = _make_settings()
        classifier = Classifier(settings)

        ai_response = {
            "summary": "Amazon product page for wireless earbuds",
            "suggestions": [
                {"category": "wishlist", "confidence": 0.95, "reason": "Product link"},
                {"category": "useful_links", "confidence": 0.3, "reason": "It's a link"},
            ],
        }

        with patch.object(classifier._client.aio.models, "generate_content", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_gemini_response(ai_response)

            payload = _make_payload(
                raw_text="https://amazon.com/dp/B09XYZ",
                url="https://amazon.com/dp/B09XYZ",
                message_type=MessageType.LINK,
            )
            result = await classifier.classify(payload)

            assert result.suggestions[0].category == "wishlist"
            assert result.suggestions[0].confidence == 0.95
            assert result.ai_summary == "Amazon product page for wireless earbuds"

    @pytest.mark.asyncio
    async def test_movie_name_classified_as_watch_later(self):
        """A movie name should be classified as 'watch_later'."""
        settings = _make_settings()
        classifier = Classifier(settings)

        ai_response = {
            "summary": "Movie recommendation: Inception",
            "suggestions": [
                {"category": "watch_later", "confidence": 0.9, "reason": "Movie name"},
            ],
        }

        with patch.object(classifier._client.aio.models, "generate_content", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_gemini_response(ai_response)

            payload = _make_payload(raw_text="Need to watch Inception")
            result = await classifier.classify(payload)

            assert result.suggestions[0].category == "watch_later"

    @pytest.mark.asyncio
    async def test_malformed_response_falls_back_to_other(self):
        """Malformed AI response should gracefully fall back to 'other'."""
        settings = _make_settings()
        classifier = Classifier(settings)

        with patch.object(classifier._client.aio.models, "generate_content", new_callable=AsyncMock) as mock_gen:
            mock_gen.side_effect = Exception("API error")

            payload = _make_payload(raw_text="Some random content")
            result = await classifier.classify(payload)

            assert len(result.suggestions) == 1
            assert result.suggestions[0].category == "other"
            assert result.suggestions[0].confidence == 1.0

    @pytest.mark.asyncio
    async def test_unknown_category_mapped_to_other(self):
        """Unknown category slugs from AI should be mapped to 'other'."""
        settings = _make_settings()
        classifier = Classifier(settings)

        ai_response = {
            "summary": "Something weird",
            "suggestions": [
                {"category": "nonexistent_category", "confidence": 0.8, "reason": "Test"},
            ],
        }

        with patch.object(classifier._client.aio.models, "generate_content", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_gemini_response(ai_response)

            payload = _make_payload(raw_text="test")
            result = await classifier.classify(payload)

            assert result.suggestions[0].category == "other"

    @pytest.mark.asyncio
    async def test_empty_suggestions_gets_fallback(self):
        """Empty suggestions array from AI should get a fallback."""
        settings = _make_settings()
        classifier = Classifier(settings)

        ai_response = {"summary": "Empty", "suggestions": []}

        with patch.object(classifier._client.aio.models, "generate_content", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = _mock_gemini_response(ai_response)

            payload = _make_payload(raw_text="test")
            result = await classifier.classify(payload)

            assert len(result.suggestions) >= 1
            assert result.suggestions[0].category == "other"
