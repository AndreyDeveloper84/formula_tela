"""T-13 RED: run() entrypoint — branching polling/webhook + error handling."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_run_polling_mode(monkeypatch):
    """MAX_BOT_MODE=polling → delete_webhook + start_polling."""
    monkeypatch.setenv("MAX_BOT_TOKEN", "x")
    monkeypatch.setenv("MAX_BOT_MODE", "polling")

    fake_bot = MagicMock()
    fake_bot.get_me = AsyncMock(return_value=MagicMock(user_id=1, username="b"))
    fake_bot.delete_webhook = AsyncMock()

    fake_dp = MagicMock()
    fake_dp.start_polling = AsyncMock()
    fake_dp.handle_webhook = AsyncMock()

    with patch("maxbot.main.Bot", return_value=fake_bot), \
         patch("maxbot.main.build_dispatcher", return_value=fake_dp):
        from maxbot.main import run
        await run()

    fake_bot.delete_webhook.assert_awaited_once()
    fake_dp.start_polling.assert_awaited_once_with(fake_bot)
    fake_dp.handle_webhook.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_webhook_mode(monkeypatch):
    """MAX_BOT_MODE=webhook → handle_webhook with config (host/port/path/secret)."""
    monkeypatch.setenv("MAX_BOT_TOKEN", "x")
    monkeypatch.setenv("MAX_BOT_MODE", "webhook")
    monkeypatch.setenv("MAX_WEBHOOK_HOST", "127.0.0.1")
    monkeypatch.setenv("MAX_WEBHOOK_PORT", "8003")
    monkeypatch.setenv("MAX_WEBHOOK_PATH", "/api/maxbot/webhook/")
    monkeypatch.setenv("MAX_WEBHOOK_SECRET", "topsecret")

    fake_bot = MagicMock()
    fake_bot.get_me = AsyncMock(return_value=MagicMock(user_id=1, username="b"))

    fake_dp = MagicMock()
    fake_dp.start_polling = AsyncMock()
    fake_dp.handle_webhook = AsyncMock()

    with patch("maxbot.main.Bot", return_value=fake_bot), \
         patch("maxbot.main.build_dispatcher", return_value=fake_dp):
        from maxbot.main import run
        await run()

    fake_dp.handle_webhook.assert_awaited_once()
    call = fake_dp.handle_webhook.await_args
    assert call.kwargs["bot"] is fake_bot
    assert call.kwargs["host"] == "127.0.0.1"
    assert call.kwargs["port"] == 8003
    assert call.kwargs["path"] == "/api/maxbot/webhook/"
    assert call.kwargs["secret"] == "topsecret"
    fake_dp.start_polling.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_webhook_secret_none_when_empty(monkeypatch):
    """Пустой MAX_WEBHOOK_SECRET → secret=None в handle_webhook (SDK не валидирует header)."""
    monkeypatch.setenv("MAX_BOT_TOKEN", "x")
    monkeypatch.setenv("MAX_BOT_MODE", "webhook")
    monkeypatch.delenv("MAX_WEBHOOK_SECRET", raising=False)

    fake_bot = MagicMock()
    fake_bot.get_me = AsyncMock(return_value=MagicMock(user_id=1, username="b"))
    fake_dp = MagicMock()
    fake_dp.handle_webhook = AsyncMock()

    with patch("maxbot.main.Bot", return_value=fake_bot), \
         patch("maxbot.main.build_dispatcher", return_value=fake_dp):
        from maxbot.main import run
        await run()
    assert fake_dp.handle_webhook.await_args.kwargs["secret"] is None


@pytest.mark.asyncio
async def test_run_invalid_token_friendly_error(monkeypatch):
    """bot.get_me падает на невалидном токене → friendly hint в логе + re-raise."""
    monkeypatch.setenv("MAX_BOT_TOKEN", "bad-token")
    monkeypatch.setenv("MAX_BOT_MODE", "polling")

    fake_bot = MagicMock()
    fake_bot.get_me = AsyncMock(side_effect=RuntimeError("Invalid token"))
    fake_dp = MagicMock()

    with patch("maxbot.main.Bot", return_value=fake_bot), \
         patch("maxbot.main.build_dispatcher", return_value=fake_dp), \
         patch("maxbot.main.logger") as mock_logger:
        from maxbot.main import run
        with pytest.raises(RuntimeError):
            await run()
        # Должен быть лог про MAX_BOT_TOKEN
        log_calls = " ".join(str(c) for c in mock_logger.error.call_args_list)
        assert "MAX_BOT_TOKEN" in log_calls
