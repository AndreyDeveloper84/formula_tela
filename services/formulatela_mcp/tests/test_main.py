"""T-03 RED: skeleton MCP-сервера — импортируется, ping() tool работает."""
import pytest


def test_main_module_importable():
    """from formulatela_mcp.main import mcp — без ImportError."""
    from formulatela_mcp.main import mcp, ping, cli
    assert mcp is not None
    assert callable(ping)
    assert callable(cli)


def test_ping_tool_returns_pong():
    """ping() напрямую возвращает 'pong'."""
    from formulatela_mcp.main import ping
    assert ping() == "pong"


def test_mcp_has_ping_tool_registered():
    """FastMCP зарегистрировал ping как tool (через @mcp.tool() декоратор)."""
    from formulatela_mcp.main import mcp
    # FastMCP API: list_tools / get_tools / _tools — структура зависит от версии SDK.
    # Проверяем самым устойчивым способом — атрибут tools или метод list.
    tool_names = []
    if hasattr(mcp, "_tool_manager"):
        tool_names = list(mcp._tool_manager._tools.keys())
    elif hasattr(mcp, "tools"):
        tool_names = list(mcp.tools.keys()) if hasattr(mcp.tools, "keys") else [t.name for t in mcp.tools]
    assert "ping" in tool_names, f"ping не найден в tools: {tool_names}"


def test_django_bootstrap_idempotent():
    from formulatela_mcp.django_bootstrap import setup_django
    setup_django()
    setup_django()  # second call no-op
    from django.conf import settings
    assert settings.configured
