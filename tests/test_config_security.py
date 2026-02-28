import json
from pathlib import Path
from unittest.mock import patch

from src.config import ConfigManager


from typing import Dict, Optional

def _build_manager(tmp_path: Path, monkeypatch, env: Optional[Dict[str, str]] = None):
    config_path = tmp_path / "config.json"
    monkeypatch.setenv("NEWS_SCRAPER_OPENAI_API_KEY", "", prepend=False)
    monkeypatch.setenv("NEWS_SCRAPER_NEWS_API_KEY", "", prepend=False)

    if env:
        for key, value in env.items():
            monkeypatch.setenv(key, value)

    with patch.object(ConfigManager, "get_config_path", return_value=str(config_path)):
        return ConfigManager(), config_path


def test_environment_keys_override_persisted_keys(tmp_path, monkeypatch):
    manager, config_path = _build_manager(
        tmp_path,
        monkeypatch,
        env={
            "NEWS_SCRAPER_OPENAI_API_KEY": "env-openai-key",
            "NEWS_SCRAPER_NEWS_API_KEY": "env-news-key",
        },
    )

    manager.save_config(
        {
            **manager.config,
            "OPENAI_API_KEY": "persisted-openai-key",
            "NEWS_API_KEY": "persisted-news-key",
        }
    )

    with patch.object(ConfigManager, "get_config_path", return_value=str(config_path)):
        reloaded = ConfigManager()

    assert reloaded.get("OPENAI_API_KEY") == "env-openai-key"
    assert reloaded.get("NEWS_API_KEY") == "env-news-key"


def test_save_config_never_writes_sensitive_keys_to_config_json(tmp_path, monkeypatch):
    manager, config_path = _build_manager(tmp_path, monkeypatch)

    manager.save_config(
        {
            "NEWS_API_KEY": "news-key",
            "OPENAI_API_KEY": "openai-key",
            "RELEVANCE_THRESHOLD": 0.8,
        }
    )

    content = json.loads(config_path.read_text(encoding="utf-8"))
    assert "NEWS_API_KEY" not in content
    assert "OPENAI_API_KEY" not in content
    assert content["RELEVANCE_THRESHOLD"] == 0.8
