"""MCP-сервер entrypoint.

Запуск:
    python -m formulatela_mcp.main          # stdio (для subprocess из maxbot)
    formulatela-mcp                          # альтернативный CLI (см. pyproject [project.scripts])
"""
from __future__ import annotations

# Django до импорта tools/ — те читают ORM
from formulatela_mcp.django_bootstrap import setup_django
setup_django()

from mcp.server.fastmcp import FastMCP  # noqa: E402


mcp = FastMCP("formulatela-mcp")


@mcp.tool()
def ping() -> str:
    """Sanity check — MCP-сервер жив и доступен из клиента.

    Используется maxbot'ом при инициализации persistent-сессии для проверки
    что subprocess успешно поднялся.
    """
    return "pong"


# T-05: search_faq будет здесь
# T-XX (Фаза 2.2): search_services
# T-XX (Фаза 2.3): find_master, find_slot, book_via_yclients


def cli() -> None:
    """Entry-point для console_script (см. pyproject)."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    cli()
