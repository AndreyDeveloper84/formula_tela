"""T06: ai_concierge.py — main chat pipeline (replaces chat_rag for AI Concierge)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

pytestmark = pytest.mark.django_db(transaction=True)

amake = sync_to_async(baker.make, thread_sensitive=True)


def _mock_openai_completion(content: str = "ответ", tool_calls=None,
                            tokens_in: int = 100, tokens_out: int = 50):
    """Mock OpenAI ChatCompletion ответа."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = msg

    usage = MagicMock()
    usage.prompt_tokens = tokens_in
    usage.completion_tokens = tokens_out

    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = usage
    return completion


def _mock_tool_call(name: str, args: dict):
    """Mock OpenAI tool_call object."""
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    tc.id = "call_test"
    return tc


def _mock_openai_client(completion):
    """Mock AsyncOpenAI client возвращающий заданный completion."""
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=completion)
    return client


# ─── _resolve_conversation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_conversation_creates_new_when_none_active():
    from maxbot.ai_concierge import _resolve_conversation
    from services_app.models import BotUser, Conversation

    bu = await amake(BotUser, max_user_id=90001)
    conv = await _resolve_conversation(bu)
    assert conv.bot_user_id == bu.pk
    assert conv.is_active is True


@pytest.mark.asyncio
async def test_resolve_conversation_reuses_existing_active():
    from maxbot.ai_concierge import _resolve_conversation
    from services_app.models import BotUser, Conversation

    bu = await amake(BotUser, max_user_id=90002)
    existing = await sync_to_async(Conversation.objects.create)(bot_user=bu)
    conv = await _resolve_conversation(bu)
    assert conv.id == existing.id


@pytest.mark.asyncio
async def test_resolve_conversation_skips_closed():
    """Закрытый conversation (is_active=False) → создаём новый."""
    from maxbot.ai_concierge import _resolve_conversation
    from services_app.models import BotUser, Conversation

    bu = await amake(BotUser, max_user_id=90003)
    closed = await sync_to_async(Conversation.objects.create)(
        bot_user=bu, is_active=False,
    )
    conv = await _resolve_conversation(bu)
    assert conv.id != closed.id
    assert conv.is_active is True


# ─── _save_message ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_save_user_message():
    from maxbot.ai_concierge import _save_message
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=90010)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu)
    msg = await _save_message(conv, role=Message.Role.USER, content="Привет")
    assert msg.role == "user"
    assert msg.content == "Привет"
    assert msg.action_type == ""


@pytest.mark.asyncio
async def test_save_assistant_message_with_action_and_telemetry():
    from maxbot.ai_concierge import _save_message
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=90011)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu)
    msg = await _save_message(
        conv, role=Message.Role.ASSISTANT,
        content="Я нашёл вам:",
        action_type="show_masters",
        action_data={"masters": []},
        tokens_in=120, tokens_out=45, latency_ms=2300,
    )
    assert msg.action_type == "show_masters"
    assert msg.action_data == {"masters": []}
    assert msg.tokens_in == 120
    assert msg.latency_ms == 2300


# ─── _load_recent_history ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_load_recent_history_returns_chronological():
    """История идёт ASC by created_at — для LLM."""
    from maxbot.ai_concierge import _load_recent_history
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=90020)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu)
    m1 = await sync_to_async(Message.objects.create)(
        conversation=conv, role="user", content="1")
    m2 = await sync_to_async(Message.objects.create)(
        conversation=conv, role="assistant", content="2")
    m3 = await sync_to_async(Message.objects.create)(
        conversation=conv, role="user", content="3")

    history = await _load_recent_history(conv, exclude_id=None, limit=10)
    assert [m.pk for m in history] == [m1.pk, m2.pk, m3.pk]


@pytest.mark.asyncio
async def test_load_recent_history_respects_limit():
    from maxbot.ai_concierge import _load_recent_history
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=90021)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu)
    for i in range(15):
        await sync_to_async(Message.objects.create)(
            conversation=conv, role="user", content=str(i))

    history = await _load_recent_history(conv, exclude_id=None, limit=5)
    assert len(history) == 5
    # Последние 5 в хронологическом порядке (10, 11, 12, 13, 14)
    assert [m.content for m in history] == ["10", "11", "12", "13", "14"]


@pytest.mark.asyncio
async def test_load_recent_history_excludes_id():
    """Только что сохранённое user-сообщение исключаем — оно идёт отдельно в LLM."""
    from maxbot.ai_concierge import _load_recent_history
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=90022)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu)
    m1 = await sync_to_async(Message.objects.create)(
        conversation=conv, role="user", content="старое")
    m2 = await sync_to_async(Message.objects.create)(
        conversation=conv, role="user", content="новое")

    history = await _load_recent_history(conv, exclude_id=m2.id, limit=10)
    assert [m.pk for m in history] == [m1.pk]


# ─── send_message — happy path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_simple_text_response_no_tool_call():
    """LLM отвечает обычным текстом без tool_call → action_type=None."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser

    bu = await amake(BotUser, max_user_id=90100, client_name="Анна")
    completion = _mock_openai_completion(content="Привет, Анна!")
    openai_client = _mock_openai_client(completion)

    dto = await send_message(
        bot_user=bu, message_text="Привет",
        openai_client=openai_client,
    )
    assert dto.content == "Привет, Анна!"
    assert dto.action_type is None
    assert dto.action_data is None


@pytest.mark.asyncio
async def test_send_message_with_show_masters_tool_call():
    """LLM эмиттит show_masters → handler validates → action_data в DTO."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser, Master, Service

    bu = await amake(BotUser, max_user_id=90101)
    svc = await amake(Service, name="Массаж")
    master = await amake(Master, name="Анна", is_active=True)
    await sync_to_async(master.services.add)(svc)

    tc = _mock_tool_call("show_masters", {
        "master_ids": [master.id],
        "explanation": "подходит",
    })
    completion = _mock_openai_completion(content="", tool_calls=[tc])
    openai_client = _mock_openai_client(completion)

    dto = await send_message(
        bot_user=bu, message_text="хочу к мастеру",
        openai_client=openai_client,
    )
    assert dto.action_type == "show_masters"
    assert len(dto.action_data["masters"]) == 1
    assert dto.action_data["masters"][0]["master"]["id"] == master.id


@pytest.mark.asyncio
async def test_send_message_persists_user_and_assistant_messages():
    """После send_message в Conversation 2 сообщения: user + assistant."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=90102)
    completion = _mock_openai_completion(content="ответ от LLM")
    openai_client = _mock_openai_client(completion)

    dto = await send_message(
        bot_user=bu, message_text="вопрос",
        openai_client=openai_client,
    )

    conv = await sync_to_async(Conversation.objects.get)(id=dto.conversation_id)
    msgs = await sync_to_async(list)(conv.messages.all().order_by("created_at"))
    assert len(msgs) == 2
    assert msgs[0].role == "user"
    assert msgs[0].content == "вопрос"
    assert msgs[1].role == "assistant"
    assert msgs[1].content == "ответ от LLM"


@pytest.mark.asyncio
async def test_send_message_saves_telemetry():
    """tokens_in/out + latency_ms сохраняются в assistant Message."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser, Message

    bu = await amake(BotUser, max_user_id=90103)
    completion = _mock_openai_completion(content="x", tokens_in=200, tokens_out=80)
    openai_client = _mock_openai_client(completion)

    await send_message(
        bot_user=bu, message_text="x",
        openai_client=openai_client,
    )
    asst = await sync_to_async(Message.objects.filter(role="assistant").last)()
    assert asst.tokens_in == 200
    assert asst.tokens_out == 80
    assert asst.latency_ms is not None and asst.latency_ms >= 0


@pytest.mark.asyncio
async def test_send_message_passes_history_to_openai():
    """Последние messages идут в LLM как messages context."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser, Conversation, Message

    bu = await amake(BotUser, max_user_id=90104)
    conv = await sync_to_async(Conversation.objects.create)(bot_user=bu)
    await sync_to_async(Message.objects.create)(
        conversation=conv, role="user", content="старый вопрос")
    await sync_to_async(Message.objects.create)(
        conversation=conv, role="assistant", content="старый ответ")

    completion = _mock_openai_completion(content="новый ответ")
    openai_client = _mock_openai_client(completion)

    await send_message(
        bot_user=bu, message_text="новый вопрос",
        openai_client=openai_client,
    )
    # OpenAI вызван с messages включающими историю
    call_args = openai_client.chat.completions.create.await_args
    messages = call_args.kwargs["messages"]
    contents = [m["content"] for m in messages]
    # должны быть system + старые user/assistant + новый user
    assert any("старый вопрос" in c for c in contents)
    assert any("старый ответ" in c for c in contents)
    assert any("новый вопрос" in c for c in contents)


@pytest.mark.asyncio
async def test_send_message_calls_openai_with_tool_definitions():
    """OpenAI вызван с tools= TOOL_DEFINITIONS — без них LLM не сможет эмиттить."""
    from maxbot.ai_concierge import send_message
    from maxbot.ai_tools import TOOL_DEFINITIONS
    from services_app.models import BotUser

    bu = await amake(BotUser, max_user_id=90105)
    completion = _mock_openai_completion(content="x")
    openai_client = _mock_openai_client(completion)

    await send_message(
        bot_user=bu, message_text="x",
        openai_client=openai_client,
    )
    call_args = openai_client.chat.completions.create.await_args
    tools_passed = call_args.kwargs.get("tools")
    assert tools_passed == TOOL_DEFINITIONS


@pytest.mark.asyncio
async def test_send_message_invalid_tool_call_falls_back():
    """LLM эмиттит unknown tool → handler fallback → action_type=ask_clarification."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser

    bu = await amake(BotUser, max_user_id=90106)
    tc = _mock_tool_call("unknown_tool", {})
    completion = _mock_openai_completion(content="", tool_calls=[tc])
    openai_client = _mock_openai_client(completion)

    dto = await send_message(
        bot_user=bu, message_text="x",
        openai_client=openai_client,
    )
    assert dto.action_type == "ask_clarification"


# ─── Failure modes ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_message_openai_failure_raises_unavailable():
    """OpenAI network error → exception (caller обрабатывает graceful)."""
    from maxbot.ai_concierge import send_message
    from services_app.models import BotUser

    bu = await amake(BotUser, max_user_id=90107)
    openai_client = MagicMock()
    openai_client.chat.completions.create = AsyncMock(
        side_effect=RuntimeError("OpenAI 503"),
    )

    with pytest.raises(RuntimeError):
        await send_message(
            bot_user=bu, message_text="x",
            openai_client=openai_client,
        )


# ─── Promise-without-tool retry (FT-fix) ──────────────────────────────────


def test_looks_like_promise_without_tool_detects_stems():
    from maxbot.ai_concierge import _looks_like_promise_without_tool
    cases = [
        "Я подберу несколько подходящих услуг. Подождите немного.",  # подбер + подождит
        "Сейчас гляну свободное время",                              # гляну
        "Поняла, посмотрим что есть",                                # посмотр
        "Вот варианты для вас:",                                     # вот вариант
        "Давайте уточним детали",                                    # давайте уточн
        "Подождите минуточку",                                       # подождит + минуточк
        "Уточню и вернусь",                                          # уточню
        "Помогу выбрать подходящее",                                 # помогу выбрать
        "Рассмотрим массажи которые подойдут",                       # рассмотр
    ]
    for c in cases:
        assert _looks_like_promise_without_tool(c), f"should match: {c!r}"


def test_looks_like_promise_without_tool_skips_normal_text():
    from maxbot.ai_concierge import _looks_like_promise_without_tool
    safe = [
        "Здравствуйте! Чем могу помочь?",
        "Я отвечаю на вопросы о массаже и SPA в нашем салоне.",
        "У нас три направления — массаж, лазерная эпиляция и уход за лицом.",
        "",
        None,
    ]
    for c in safe:
        assert not _looks_like_promise_without_tool(c), f"should NOT match: {c!r}"
