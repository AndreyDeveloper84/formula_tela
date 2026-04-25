"""LLM-утилиты для AI-помощника MAX-бота.

- `get_async_openai_client()` — AsyncOpenAI с поддержкой HTTPS-прокси
  (api.openai.com заблокирован в РФ; паттерн из agents/agents/__init__.py
  но async версия)
- `mcp_tools_to_openai_schema(mcp_tools)` — конвертер MCP tool definitions
  → OpenAI tools schema (оба используют JSON Schema, ~10 строк glue)
- `chat_with_tools(...)` — главный loop: chat.completions.create с tools,
  если tool_calls → выполнить через MCP-клиент, повторить. Защита от
  бесконечной петли через max_iterations.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from openai import AsyncOpenAI

from maxbot.mcp_client import MaxbotMCPClient


logger = logging.getLogger("maxbot.llm")

# Дефолтная модель — gpt-4o-mini (дёшево, хороший tool-use)
DEFAULT_MODEL = "gpt-4o-mini"

# Защита от бесконечного цикла tool-use
MAX_TOOL_ITERATIONS = 5

# Сообщение клиенту когда модель не справилась за лимит
LLM_GIVEUP_MESSAGE = "Не получилось разобраться. Передаю вопрос менеджеру."


def get_async_openai_client() -> AsyncOpenAI:
    """AsyncOpenAI с прокси из OPENAI_PROXY (для async-handler'ов maxbot)."""
    kwargs: dict[str, Any] = {"api_key": settings.OPENAI_API_KEY}
    if getattr(settings, "OPENAI_BASE_URL", ""):
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    proxy = getattr(settings, "OPENAI_PROXY", "")
    if proxy:
        import httpx
        kwargs["http_client"] = httpx.AsyncClient(proxy=proxy)
    return AsyncOpenAI(**kwargs)


def mcp_tools_to_openai_schema(mcp_tools: list[Any]) -> list[dict]:
    """Конвертирует MCP tool definitions в OpenAI tools schema.

    MCP `Tool(name, description, inputSchema)` → OpenAI
    `{type: "function", function: {name, description, parameters: <JSON Schema>}}`.

    Оба используют JSON Schema для parameters → передаём как есть.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": getattr(tool, "description", "") or "",
                "parameters": getattr(tool, "inputSchema", None) or {
                    "type": "object",
                    "properties": {},
                },
            },
        }
        for tool in mcp_tools
    ]


async def chat_with_tools(
    *,
    messages: list[dict],
    mcp_client: MaxbotMCPClient,
    model: str = DEFAULT_MODEL,
    max_iterations: int = MAX_TOOL_ITERATIONS,
    openai_client: AsyncOpenAI | None = None,
) -> str:
    """Tool-use loop: LLM может вызывать MCP-tools для ответа на запрос.

    `messages` стартовый список (system + user). Loop модифицирует копию.
    Возвращает финальный текст для клиента.

    При превышении max_iterations — возвращает LLM_GIVEUP_MESSAGE (caller
    должен создать BotInquiry для менеджера).
    """
    await mcp_client.ensure_started()
    tools_schema = mcp_tools_to_openai_schema(mcp_client.list_tools())
    client = openai_client or get_async_openai_client()
    msgs = list(messages)

    for iteration in range(max_iterations):
        resp = await client.chat.completions.create(
            model=model,
            messages=msgs,
            tools=tools_schema,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            # Финальный ответ
            return msg.content or ""

        # Сохраняем assistant-сообщение с tool_calls
        msgs.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ],
        })

        # Выполняем каждый tool через MCP, ответ кладём в messages
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}
            try:
                result = await mcp_client.call_tool(tc.function.name, args)
                content = result.content[0].text if result.content else ""
            except Exception as exc:  # noqa: BLE001
                logger.exception("MCP tool %s failed", tc.function.name)
                content = json.dumps({"error": str(exc)})
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": content,
            })

    logger.warning("chat_with_tools: hit max_iterations=%d, giving up", max_iterations)
    return LLM_GIVEUP_MESSAGE
