"""Phase 2 Learning Roadmap: analyze_failed_conversations Celery task tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from model_bakery import baker

pytestmark = pytest.mark.django_db


@pytest.fixture
def failed_convs():
    """Создаёт 5 закрытых conversations с разными outcome."""
    from services_app.models import BotUser, Conversation, Message

    outcomes = ["abandoned", "redirected", "error", "abandoned", "redirected"]
    convs = []
    for i, outcome in enumerate(outcomes):
        bu = baker.make(BotUser, max_user_id=93000 + i)
        conv = Conversation.objects.create(bot_user=bu, is_active=False, outcome=outcome)
        Message.objects.create(
            conversation=conv, role="user",
            content=f"Хочу записаться на {['массаж', 'маникюр', 'уход', 'лпг', 'обёртывание'][i]}",
        )
        Message.objects.create(
            conversation=conv, role="assistant",
            content="", action_type="show_slots", action_data={"slots": []},
        )
        convs.append(conv)
    return convs


def _mock_openai_json(result: dict):
    """Mock sync OpenAI client возвращающий JSON с заданным result."""
    import json
    client = MagicMock()
    choice = MagicMock()
    choice.message.content = json.dumps(result)
    completion = MagicMock()
    completion.choices = [choice]
    client.chat.completions.create = MagicMock(return_value=completion)
    return client


# ─── Happy path ────────────────────────────────────────────────────────────


def test_analyze_returns_patterns_and_prompt_additions(failed_convs):
    """Task анализирует failed conversations и возвращает patterns/prompt_additions."""
    from services_app.tasks import analyze_failed_conversations

    llm_result = {
        "patterns": ["Бот не предлагает альтернативу при пустых слотах"],
        "weak_intents": ["запрос конкретного времени"],
        "prompt_additions": ["Если слоты пустые — всегда предлагай +1/+3/+7 дней"],
        "summary": "Основная проблема — отсутствие fallback при пустых слотах.",
    }
    mock_client = _mock_openai_json(llm_result)

    with patch("services_app.tasks.send_notification_telegram"):
        result = analyze_failed_conversations(openai_client=mock_client)

    assert result["sample_count"] == 5
    assert result["patterns"] == llm_result["patterns"]
    assert result["prompt_additions"] == llm_result["prompt_additions"]
    assert result["weak_intents"] == llm_result["weak_intents"]
    assert result["summary"] == llm_result["summary"]


def test_analyze_calls_openai_with_conversation_excerpts(failed_convs):
    """LLM вызван с текстом содержащим user-сообщения из conversations."""
    from services_app.tasks import analyze_failed_conversations

    mock_client = _mock_openai_json({
        "patterns": [], "weak_intents": [], "prompt_additions": [], "summary": "",
    })

    with patch("services_app.tasks.send_notification_telegram"):
        analyze_failed_conversations(openai_client=mock_client)

    call_kwargs = mock_client.chat.completions.create.call_args.kwargs
    messages = call_kwargs["messages"]
    # User-content должен включать хотя бы одно сообщение из conversations
    user_content = next(m["content"] for m in messages if m["role"] == "user")
    assert "Хочу записаться" in user_content
    assert "outcome=abandoned" in user_content or "outcome=redirected" in user_content


def test_analyze_sends_telegram_report(failed_convs):
    """После успешного анализа Telegram-отчёт отправлен."""
    from services_app.tasks import analyze_failed_conversations

    mock_client = _mock_openai_json({
        "patterns": ["паттерн 1"],
        "weak_intents": [],
        "prompt_additions": ["добавить правило X"],
        "summary": "Краткий вывод.",
    })

    with patch("services_app.tasks.send_notification_telegram") as mock_tg:
        analyze_failed_conversations(openai_client=mock_client)

    mock_tg.assert_called_once()
    report_text = mock_tg.call_args.args[0]
    assert "Learning Report" in report_text
    assert "паттерн 1" in report_text
    assert "добавить правило X" in report_text


# ─── Edge cases ────────────────────────────────────────────────────────────


def test_analyze_skips_when_no_failed_conversations():
    """Нет неудавшихся conversations → task возвращает skipped=True без LLM call."""
    from services_app.tasks import analyze_failed_conversations

    mock_client = _mock_openai_json({})

    with patch("services_app.tasks.send_notification_telegram") as mock_tg:
        result = analyze_failed_conversations(openai_client=mock_client)

    assert result == {"sample_count": 0, "skipped": True}
    mock_client.chat.completions.create.assert_not_called()
    mock_tg.assert_not_called()


def test_analyze_handles_openai_error_gracefully(failed_convs):
    """OpenAI падает → task возвращает error dict, не крашит worker."""
    from services_app.tasks import analyze_failed_conversations

    mock_client = MagicMock()
    mock_client.chat.completions.create = MagicMock(
        side_effect=RuntimeError("OpenAI 503")
    )

    with patch("services_app.tasks.send_notification_telegram") as mock_tg:
        result = analyze_failed_conversations(openai_client=mock_client)

    assert "error" in result
    assert result["sample_count"] == 5
    mock_tg.assert_not_called()  # не шлём при ошибке


def test_analyze_only_processes_failed_outcomes():
    """Только outcome ∈ {abandoned, redirected, error} — success-conversations не берём."""
    from services_app.models import BotUser, Conversation
    from services_app.tasks import analyze_failed_conversations

    bu = baker.make(BotUser, max_user_id=93010)
    # Одна успешная — не должна попасть в анализ
    Conversation.objects.create(bot_user=bu, is_active=False, outcome="success")

    mock_client = _mock_openai_json({})

    with patch("services_app.tasks.send_notification_telegram"):
        result = analyze_failed_conversations(openai_client=mock_client)

    # sample_count=0 потому что нет failed conversations
    assert result["sample_count"] == 0
    mock_client.chat.completions.create.assert_not_called()
