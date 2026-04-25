"""T-06a: MaxbotMCPClient — singleton с persistent stdio-сессией.

Тесты mock'ают stdio_client / ClientSession чтобы не спавнить реальный
subprocess в CI.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from maxbot.mcp_client import MaxbotMCPClient


@pytest.fixture(autouse=True)
def reset_singleton():
    """Между тестами сбрасываем singleton."""
    MaxbotMCPClient.reset_for_tests()
    yield
    MaxbotMCPClient.reset_for_tests()


# ─── Helpers ────────────────────────────────────────────────────────────────


def _patched_mcp(tool_names: list[str], call_result_text: str = '"pong"'):
    """Контекст-менеджер: подменяет stdio_client + ClientSession на моки.

    Возвращает (session_mock, list_tools_mock, call_tool_mock) для
    проверки вызовов в тесте.
    """
    session = AsyncMock()
    session.initialize = AsyncMock()
    list_tools_resp = MagicMock()
    list_tools_resp.tools = [MagicMock(name=n) for n in tool_names]
    # MagicMock(name='ping') — name это аргумент конструктора Mock!
    # Чтобы name был attribute — задаём явно после:
    for tool, n in zip(list_tools_resp.tools, tool_names):
        tool.name = n
    session.list_tools = AsyncMock(return_value=list_tools_resp)
    call_result = MagicMock()
    call_result.content = [MagicMock(text=call_result_text)]
    session.call_tool = AsyncMock(return_value=call_result)

    @asynccontextmanager
    async def fake_stdio_client(params):
        yield (MagicMock(), MagicMock())  # read, write

    @asynccontextmanager
    async def fake_session_ctx(read, write):
        yield session

    return session, fake_stdio_client, fake_session_ctx


# ─── Tests ──────────────────────────────────────────────────────────────────


def test_singleton_returns_same_instance():
    a = MaxbotMCPClient.instance()
    b = MaxbotMCPClient.instance()
    assert a is b


@pytest.mark.asyncio
async def test_ensure_started_initializes_session_once():
    session, stdio_ctx, session_ctx = _patched_mcp(["ping", "search_faq"])
    with patch("maxbot.mcp_client.stdio_client", stdio_ctx), \
         patch("maxbot.mcp_client.ClientSession", session_ctx):
        client = MaxbotMCPClient.instance()
        await client.ensure_started()
        await client.ensure_started()  # повторно — should be no-op
        # initialize вызван ровно один раз
        session.initialize.assert_awaited_once()
        session.list_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_tools_returns_cached():
    session, stdio_ctx, session_ctx = _patched_mcp(["ping", "search_faq"])
    with patch("maxbot.mcp_client.stdio_client", stdio_ctx), \
         patch("maxbot.mcp_client.ClientSession", session_ctx):
        client = MaxbotMCPClient.instance()
        await client.ensure_started()
        tools = client.list_tools()
        assert [t.name for t in tools] == ["ping", "search_faq"]


def test_list_tools_before_start_raises():
    client = MaxbotMCPClient.instance()
    with pytest.raises(RuntimeError, match="ensure_started"):
        client.list_tools()


@pytest.mark.asyncio
async def test_call_tool_routes_through_session():
    session, stdio_ctx, session_ctx = _patched_mcp(["ping"], call_result_text='"pong"')
    with patch("maxbot.mcp_client.stdio_client", stdio_ctx), \
         patch("maxbot.mcp_client.ClientSession", session_ctx):
        client = MaxbotMCPClient.instance()
        result = await client.call_tool("ping", {})
        session.call_tool.assert_awaited_once_with("ping", {})
        assert result.content[0].text == '"pong"'


@pytest.mark.asyncio
async def test_call_tool_auto_starts():
    """call_tool без явного ensure_started — стартует сам."""
    session, stdio_ctx, session_ctx = _patched_mcp(["ping"])
    with patch("maxbot.mcp_client.stdio_client", stdio_ctx), \
         patch("maxbot.mcp_client.ClientSession", session_ctx):
        client = MaxbotMCPClient.instance()
        await client.call_tool("ping", {})
        session.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_is_idempotent():
    session, stdio_ctx, session_ctx = _patched_mcp(["ping"])
    with patch("maxbot.mcp_client.stdio_client", stdio_ctx), \
         patch("maxbot.mcp_client.ClientSession", session_ctx):
        client = MaxbotMCPClient.instance()
        await client.ensure_started()
        await client.close()
        await client.close()  # повторное закрытие — no-op


@pytest.mark.asyncio
async def test_close_before_start_is_noop():
    client = MaxbotMCPClient.instance()
    await client.close()  # ничего не должно упасть


@pytest.mark.asyncio
async def test_restart_after_close():
    """После close можно ensure_started() ещё раз — будет новый subprocess."""
    session1, stdio_ctx, session_ctx = _patched_mcp(["ping"])
    with patch("maxbot.mcp_client.stdio_client", stdio_ctx), \
         patch("maxbot.mcp_client.ClientSession", session_ctx):
        client = MaxbotMCPClient.instance()
        await client.ensure_started()
        await client.close()
        # Заново — initialize вызывается опять
        await client.ensure_started()
        assert session1.initialize.await_count == 2


@pytest.mark.asyncio
async def test_start_failure_cleans_stack():
    """Если initialize падает — stack закрыт, повторный ensure_started возможен."""
    bad_session = AsyncMock()
    bad_session.initialize = AsyncMock(side_effect=RuntimeError("init failed"))

    @asynccontextmanager
    async def fake_stdio_client(params):
        yield (MagicMock(), MagicMock())

    @asynccontextmanager
    async def fake_session_ctx(read, write):
        yield bad_session

    with patch("maxbot.mcp_client.stdio_client", fake_stdio_client), \
         patch("maxbot.mcp_client.ClientSession", fake_session_ctx):
        client = MaxbotMCPClient.instance()
        with pytest.raises(RuntimeError, match="init failed"):
            await client.ensure_started()
        # Можно попробовать ещё раз без застрявшего session
        with pytest.raises(RuntimeError):
            await client.ensure_started()
