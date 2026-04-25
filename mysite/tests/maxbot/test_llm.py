"""T-06b: тесты maxbot/llm.py — конвертер схемы + tool-use loop."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from maxbot.llm import (
    LLM_GIVEUP_MESSAGE,
    chat_with_tools,
    get_async_openai_client,
    mcp_tools_to_openai_schema,
)


# ─── get_async_openai_client ────────────────────────────────────────────────

def test_get_async_openai_client_with_proxy(settings):
    settings.OPENAI_API_KEY = "sk-test"
    settings.OPENAI_PROXY = "http://proxy.example:3128"
    client = get_async_openai_client()
    # AsyncOpenAI с прокси — создан без ошибок
    assert client is not None


def test_get_async_openai_client_without_proxy(settings):
    settings.OPENAI_API_KEY = "sk-test"
    settings.OPENAI_PROXY = ""
    client = get_async_openai_client()
    assert client is not None


# ─── mcp_tools_to_openai_schema ─────────────────────────────────────────────

def test_schema_converter_basic():
    tool = MagicMock()
    tool.name = "search_faq"
    tool.description = "Найти FAQ"
    tool.inputSchema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    result = mcp_tools_to_openai_schema([tool])
    assert len(result) == 1
    assert result[0]["type"] == "function"
    assert result[0]["function"]["name"] == "search_faq"
    assert result[0]["function"]["description"] == "Найти FAQ"
    assert result[0]["function"]["parameters"]["properties"]["query"]["type"] == "string"


def test_schema_converter_handles_missing_description_and_schema():
    tool = MagicMock(spec=["name"])
    tool.name = "ping"
    result = mcp_tools_to_openai_schema([tool])
    assert result[0]["function"]["description"] == ""
    assert result[0]["function"]["parameters"] == {"type": "object", "properties": {}}


# ─── chat_with_tools loop ───────────────────────────────────────────────────


def _mock_mcp_client(tool_names: list[str], call_responses: dict[str, str] | None = None):
    """Мок MaxbotMCPClient с заданным набором tools и response'ами call_tool."""
    call_responses = call_responses or {}
    mock = MagicMock()
    mock.ensure_started = AsyncMock()
    mock.list_tools = MagicMock(return_value=[
        MagicMock(name=n, description=f"Tool {n}", inputSchema={"type": "object", "properties": {}})
        for n in tool_names
    ])
    # MagicMock(name=...) — это конструктор Mock, надо пере-указать атрибуты:
    for tool, n in zip(mock.list_tools.return_value, tool_names):
        tool.name = n

    async def _call(name, args):
        text = call_responses.get(name, '"ok"')
        result = MagicMock()
        result.content = [MagicMock(text=text)]
        return result
    mock.call_tool = AsyncMock(side_effect=_call)
    return mock


def _mock_openai_client_returning_text(text: str):
    """OpenAI mock который сразу возвращает финальный ответ (без tool_calls)."""
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    response = MagicMock()
    response.choices = [MagicMock(message=msg)]
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


def _mock_openai_client_tool_then_text(tool_name: str, tool_args: str, final_text: str):
    """OpenAI mock: первый ответ — tool_call, второй — финальный текст."""
    tc = MagicMock()
    tc.id = "call_1"
    tc.type = "function"
    tc.function = MagicMock()
    tc.function.name = tool_name
    tc.function.arguments = tool_args

    msg1 = MagicMock(content="", tool_calls=[tc])
    resp1 = MagicMock(choices=[MagicMock(message=msg1)])

    msg2 = MagicMock(content=final_text, tool_calls=None)
    resp2 = MagicMock(choices=[MagicMock(message=msg2)])

    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=[resp1, resp2])
    return client


@pytest.mark.asyncio
async def test_chat_returns_immediately_when_no_tool_calls():
    mcp = _mock_mcp_client(["ping"])
    openai = _mock_openai_client_returning_text("Прямой ответ модели")
    result = await chat_with_tools(
        messages=[{"role": "user", "content": "hi"}],
        mcp_client=mcp,
        openai_client=openai,
    )
    assert result == "Прямой ответ модели"
    mcp.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_executes_tool_call_then_returns_text():
    mcp = _mock_mcp_client(["search_faq"], call_responses={
        "search_faq": '[{"question":"Как записаться?","answer":"Через бот","score":0.9}]',
    })
    openai = _mock_openai_client_tool_then_text(
        tool_name="search_faq",
        tool_args='{"query":"запись","k":3}',
        final_text="Запись через бот.",
    )
    result = await chat_with_tools(
        messages=[{"role": "user", "content": "Как записаться?"}],
        mcp_client=mcp,
        openai_client=openai,
    )
    mcp.call_tool.assert_awaited_once_with("search_faq", {"query": "запись", "k": 3})
    assert result == "Запись через бот."
    # Должно быть 2 вызова OpenAI: первый с tool, второй финальный
    assert openai.chat.completions.create.await_count == 2


@pytest.mark.asyncio
async def test_chat_handles_invalid_tool_arguments_json():
    """Если LLM прислал кривой JSON в arguments — passes empty {}."""
    mcp = _mock_mcp_client(["ping"], call_responses={"ping": '"pong"'})
    openai = _mock_openai_client_tool_then_text(
        tool_name="ping",
        tool_args="not valid json",
        final_text="ok",
    )
    result = await chat_with_tools(
        messages=[{"role": "user", "content": "x"}],
        mcp_client=mcp, openai_client=openai,
    )
    # Не упало; tool вызван с {}
    mcp.call_tool.assert_awaited_once_with("ping", {})
    assert result == "ok"


@pytest.mark.asyncio
async def test_chat_handles_mcp_tool_exception():
    """Если MCP-tool бросает exception — content в messages = {"error": ...}, loop продолжает."""
    mcp = _mock_mcp_client(["search_faq"])
    mcp.call_tool = AsyncMock(side_effect=RuntimeError("MCP died"))
    openai = _mock_openai_client_tool_then_text(
        tool_name="search_faq",
        tool_args="{}",
        final_text="Не нашёл, передаю менеджеру",
    )
    result = await chat_with_tools(
        messages=[{"role": "user", "content": "?"}],
        mcp_client=mcp, openai_client=openai,
    )
    # Не упало; финальный ответ модели возвращён
    assert result == "Не нашёл, передаю менеджеру"


# ─── chat_rag (RAG-as-context, новый flow для AI-помощника) ────────────────


def _mcp_with_search_faq_response(items: list[dict]):
    """MCP-клиент мок где search_faq возвращает заданный список."""
    import json as _json
    mock = MagicMock()
    mock.ensure_started = AsyncMock()
    result = MagicMock()
    result.content = [MagicMock(text=_json.dumps(items))]
    mock.call_tool = AsyncMock(return_value=result)
    return mock


@pytest.mark.asyncio
async def test_chat_rag_returns_llm_answer_when_score_high():
    from maxbot.llm import chat_rag
    mcp = _mcp_with_search_faq_response([
        {"question": "Как записаться?", "answer": "Через бот.", "score": 0.85},
    ])
    openai = _mock_openai_client_returning_text("Запись через бот.")
    result = await chat_rag(
        user_text="Хочу записаться",
        system_prompt="Ты ассистент.",
        mcp_client=mcp,
        openai_client=openai,
    )
    assert result == "Запись через бот."
    # Только ОДИН LLM call (без tools loop)
    assert openai.chat.completions.create.await_count == 1
    # search_faq вызван прямо
    mcp.call_tool.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_rag_returns_giveup_when_score_below_threshold():
    """Если top score < min_score → возврат giveup БЕЗ LLM call."""
    from maxbot.llm import chat_rag, LLM_GIVEUP_MESSAGE
    mcp = _mcp_with_search_faq_response([
        {"question": "X?", "answer": "A", "score": 0.3},
    ])
    openai = MagicMock()
    openai.chat.completions.create = AsyncMock()
    result = await chat_rag(
        user_text="любимый цвет?",
        system_prompt="...",
        mcp_client=mcp,
        openai_client=openai,
        min_score=0.5,
    )
    assert result == LLM_GIVEUP_MESSAGE
    openai.chat.completions.create.assert_not_awaited()  # сэкономили LLM call


@pytest.mark.asyncio
async def test_chat_rag_returns_giveup_when_no_faq_found():
    from maxbot.llm import chat_rag, LLM_GIVEUP_MESSAGE
    mcp = _mcp_with_search_faq_response([])
    openai = MagicMock()
    openai.chat.completions.create = AsyncMock()
    result = await chat_rag(
        user_text="?", system_prompt="...", mcp_client=mcp, openai_client=openai,
    )
    assert result == LLM_GIVEUP_MESSAGE
    openai.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_rag_returns_giveup_when_search_faq_crashes():
    from maxbot.llm import chat_rag, LLM_GIVEUP_MESSAGE
    mock = MagicMock()
    mock.ensure_started = AsyncMock()
    mock.call_tool = AsyncMock(side_effect=RuntimeError("MCP died"))
    openai = MagicMock()
    result = await chat_rag(
        user_text="?", system_prompt="...", mcp_client=mock, openai_client=openai,
    )
    assert result == LLM_GIVEUP_MESSAGE


@pytest.mark.asyncio
async def test_chat_max_iterations_returns_giveup_message():
    """Если LLM зациклил tool_calls — после max_iterations возвращаем fallback."""
    mcp = _mock_mcp_client(["ping"], call_responses={"ping": '"pong"'})

    # OpenAI всегда возвращает tool_call (бесконечный цикл)
    tc = MagicMock(id="x", type="function")
    tc.function = MagicMock(name="ping", arguments="{}")
    tc.function.name = "ping"  # повторно, т.к. name=... в Mock — конструктор

    looping_msg = MagicMock(content="", tool_calls=[tc])
    looping_resp = MagicMock(choices=[MagicMock(message=looping_msg)])

    openai = MagicMock()
    openai.chat.completions.create = AsyncMock(return_value=looping_resp)

    result = await chat_with_tools(
        messages=[{"role": "user", "content": "?"}],
        mcp_client=mcp, openai_client=openai,
        max_iterations=3,
    )
    assert result == LLM_GIVEUP_MESSAGE
    assert openai.chat.completions.create.await_count == 3
