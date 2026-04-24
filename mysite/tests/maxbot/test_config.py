"""T-03 RED: config — env-чтение MAX_BOT_TOKEN и параметров webhook."""
import pytest
from django.core.exceptions import ImproperlyConfigured


def test_config_raises_without_token(monkeypatch):
    """MAX_BOT_TOKEN отсутствует → ImproperlyConfigured."""
    monkeypatch.delenv("MAX_BOT_TOKEN", raising=False)
    from maxbot.config import get_config
    with pytest.raises(ImproperlyConfigured, match="MAX_BOT_TOKEN"):
        get_config()


def test_config_reads_token_from_env(monkeypatch):
    monkeypatch.setenv("MAX_BOT_TOKEN", "test-token-123")
    from maxbot.config import get_config
    cfg = get_config()
    assert cfg.token == "test-token-123"


def test_config_default_mode_is_polling(monkeypatch):
    """Без MAX_BOT_MODE дефолт — polling (безопасно для локалки/CI)."""
    monkeypatch.setenv("MAX_BOT_TOKEN", "x")
    monkeypatch.delenv("MAX_BOT_MODE", raising=False)
    from maxbot.config import get_config
    assert get_config().mode == "polling"


def test_config_webhook_defaults(monkeypatch):
    """Дефолтные host/port/path — для prod (127.0.0.1:8003 за nginx)."""
    monkeypatch.setenv("MAX_BOT_TOKEN", "x")
    monkeypatch.setenv("MAX_BOT_MODE", "webhook")
    from maxbot.config import get_config
    cfg = get_config()
    assert cfg.mode == "webhook"
    assert cfg.webhook_host == "127.0.0.1"
    assert cfg.webhook_port == 8003


def test_config_invalid_mode_raises(monkeypatch):
    monkeypatch.setenv("MAX_BOT_TOKEN", "x")
    monkeypatch.setenv("MAX_BOT_MODE", "garbage")
    from maxbot.config import get_config
    with pytest.raises(ImproperlyConfigured, match="MAX_BOT_MODE"):
        get_config()
