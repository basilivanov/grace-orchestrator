"""
Tests for Anthropic API integration.
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock

from prefect_grace.platform.anthropic_client import AnthropicClient
from prefect_grace.platform.model_validator import (
    validate_model,
    get_model_provider,
    list_available_models,
)
from prefect_grace.platform.api_keys import (
    get_anthropic_api_key,
    get_google_api_key,
    validate_api_keys,
)


class TestAnthropicClient:
    """Tests for AnthropicClient."""

    def test_init_with_api_key(self):
        """Test initialization with explicit API key."""
        with patch("prefect_grace.platform.anthropic_client.Anthropic") as mock_anthropic:
            client = AnthropicClient(api_key="test-key")
            assert client.api_key == "test-key"
            mock_anthropic.assert_called_once_with(api_key="test-key")

    def test_init_from_environment(self):
        """Test initialization from environment variable."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-key"}):
            with patch("prefect_grace.platform.anthropic_client.Anthropic") as mock_anthropic:
                client = AnthropicClient()
                assert client.api_key == "env-key"
                mock_anthropic.assert_called_once_with(api_key="env-key")

    def test_init_missing_api_key(self):
        """Test initialization fails without API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not found"):
                AnthropicClient()

    def test_create_message(self):
        """Test message creation."""
        with patch("prefect_grace.platform.anthropic_client.Anthropic") as mock_anthropic:
            # Setup mock response
            mock_response = Mock()
            mock_response.id = "msg_123"
            mock_response.model = "claude-sonnet-4-6"
            mock_response.content = [Mock(text="Hello!")]
            mock_response.usage = Mock(input_tokens=10, output_tokens=5)
            mock_response.stop_reason = "end_turn"

            mock_client = Mock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            client = AnthropicClient(api_key="test-key")
            response = client.create_message(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=100,
            )

            assert response["id"] == "msg_123"
            assert response["model"] == "claude-sonnet-4-6"
            assert response["content"] == "Hello!"
            assert response["usage"]["input_tokens"] == 10
            assert response["usage"]["output_tokens"] == 5
            assert response["stop_reason"] == "end_turn"

    def test_create_message_empty_content(self):
        """Test message creation with empty content."""
        with patch("prefect_grace.platform.anthropic_client.Anthropic") as mock_anthropic:
            # Setup mock response with empty content
            mock_response = Mock()
            mock_response.id = "msg_123"
            mock_response.model = "claude-sonnet-4-6"
            mock_response.content = []
            mock_response.usage = Mock(input_tokens=10, output_tokens=0)
            mock_response.stop_reason = "end_turn"

            mock_client = Mock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            client = AnthropicClient(api_key="test-key")
            response = client.create_message(
                model="claude-sonnet-4-6",
                messages=[{"role": "user", "content": "Hi"}],
            )

            assert response["content"] == ""


class TestModelValidator:
    """Tests for model validation."""

    def test_validate_model_supported(self):
        """Test validation of supported models."""
        assert validate_model("claude-opus-4") is True
        assert validate_model("claude-sonnet-4-6") is True
        assert validate_model("gemini-3.5-flash") is True

    def test_validate_model_unsupported(self):
        """Test validation of unsupported models."""
        assert validate_model("gpt-4") is False
        assert validate_model("gpt-5") is False
        assert validate_model("unknown-model") is False

    def test_get_model_provider(self):
        """Test getting model provider."""
        assert get_model_provider("claude-opus-4") == "anthropic"
        assert get_model_provider("gemini-3.5-flash") == "google"
        assert get_model_provider("unknown-model") == "unknown"

    def test_list_available_models(self):
        """Test listing available models."""
        models = list_available_models()
        assert "claude-opus-4" in models
        assert "claude-sonnet-4-6" in models
        assert "gemini-3.5-flash" in models
        assert "gpt-4" not in models

    def test_list_available_models_by_provider(self):
        """Test listing models filtered by provider."""
        anthropic_models = list_available_models(provider="anthropic")
        assert all("claude" in m for m in anthropic_models)
        assert "gemini-3.5-flash" not in anthropic_models

        google_models = list_available_models(provider="google")
        assert all("gemini" in m for m in google_models)
        assert "claude-opus-4" not in google_models


class TestAPIKeys:
    """Tests for API key management."""

    def test_get_anthropic_api_key(self):
        """Test getting Anthropic API key."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            assert get_anthropic_api_key() == "test-key"

        with patch.dict(os.environ, {}, clear=True):
            assert get_anthropic_api_key() is None

    def test_get_google_api_key(self):
        """Test getting Google API key."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            assert get_google_api_key() == "test-key"

        with patch.dict(os.environ, {}, clear=True):
            assert get_google_api_key() is None

    def test_validate_api_keys(self):
        """Test API key validation."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key1", "GOOGLE_API_KEY": "key2"}):
            result = validate_api_keys()
            assert result["anthropic"] is True
            assert result["google"] is True

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key1"}):
            result = validate_api_keys()
            assert result["anthropic"] is True
            assert result["google"] is False

        with patch.dict(os.environ, {}, clear=True):
            result = validate_api_keys()
            assert result["anthropic"] is False
            assert result["google"] is False
