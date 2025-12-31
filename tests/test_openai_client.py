"""Smoke tests for OpenAI client module."""
import pytest
from unittest.mock import patch, MagicMock


class TestOpenAIClientImport:
    """Regression test for import fix."""

    def test_module_imports_without_error(self):
        """The module should import without ModuleNotFoundError."""
        from src.openai_client import get_client

        assert get_client is not None

    def test_client_instantiation_with_api_key(self):
        """Client should instantiate when API key is available."""
        with patch("src.openai_client.ConfigManager") as mock_config, patch(
            "src.openai_client.OpenAI"
        ) as mock_openai:
            mock_config.return_value.get.return_value = "test-key"
            mock_openai.return_value = MagicMock()

            from src.openai_client import get_client

            client = get_client()

            mock_config.return_value.get.assert_called_with("OPENAI_API_KEY")
            mock_openai.assert_called_once_with(api_key="test-key")
            assert client is mock_openai.return_value

    def test_client_handles_missing_api_key(self):
        """Should raise appropriate error if API key missing."""
        with patch("src.openai_client.ConfigManager") as mock_config:
            mock_config.return_value.get.return_value = None
            from src.openai_client import get_client

            with pytest.raises(ValueError):
                get_client()

