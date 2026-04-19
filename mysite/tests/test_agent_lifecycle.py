"""
Тесты страховки жизненного цикла AgentTask (P0-4).

Проверяем:
1. Нормальный путь: успешный run() → task.status == DONE
2. Исключение внутри try: → task.status == ERROR, error_message проставлено
3. Orphan-случай: таска осталась в RUNNING (например, упал сам save(ERROR))
   → ensure_task_finalized в finally приводит её в ERROR с дефолтным сообщением
4. Helper ensure_task_finalized безопасен к повторному вызову

Покрываем AnalyticsAgent и OfferAgent — остальные 5 агентов следуют
тому же шаблону (import + try/finally).
"""
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from agents.agents._lifecycle import ensure_task_finalized
from agents.models import AgentTask


# ──────────────────── Helper: ensure_task_finalized ────────────────────

@pytest.mark.django_db
def test_ensure_task_finalized_flips_running_to_error():
    task = AgentTask.objects.create(
        agent_type=AgentTask.ANALYTICS,
        status=AgentTask.RUNNING,
    )
    ensure_task_finalized(task)
    task.refresh_from_db()
    assert task.status == AgentTask.ERROR
    assert task.error_message == "Agent exited без финализации"
    assert task.finished_at is not None


@pytest.mark.django_db
def test_ensure_task_finalized_noop_on_done():
    task = AgentTask.objects.create(
        agent_type=AgentTask.ANALYTICS,
        status=AgentTask.DONE,
        finished_at=timezone.now(),
    )
    original_finished_at = task.finished_at
    ensure_task_finalized(task)
    task.refresh_from_db()
    assert task.status == AgentTask.DONE
    # finished_at не перезаписан
    assert task.finished_at == original_finished_at


@pytest.mark.django_db
def test_ensure_task_finalized_noop_on_error():
    task = AgentTask.objects.create(
        agent_type=AgentTask.ANALYTICS,
        status=AgentTask.ERROR,
        error_message="original reason",
        finished_at=timezone.now(),
    )
    ensure_task_finalized(task)
    task.refresh_from_db()
    assert task.status == AgentTask.ERROR
    assert task.error_message == "original reason"


@pytest.mark.django_db
def test_ensure_task_finalized_safe_to_call_twice():
    task = AgentTask.objects.create(
        agent_type=AgentTask.ANALYTICS,
        status=AgentTask.RUNNING,
    )
    ensure_task_finalized(task)
    # Второй вызов — без эффекта, не должен бросать
    ensure_task_finalized(task)
    task.refresh_from_db()
    assert task.status == AgentTask.ERROR


# ──────────────────── AnalyticsAgent ────────────────────

@pytest.mark.django_db
def test_analytics_agent_success_ends_done():
    from agents.agents.analytics import AnalyticsAgent

    fake_openai = MagicMock()
    fake_openai.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Анализ: всё ок."))]
    )

    with patch("agents.agents._openai_cache.get_openai_client", return_value=fake_openai), \
         patch("agents.agents.analytics.send_telegram"):
        task = AnalyticsAgent().run()

    task.refresh_from_db()
    assert task.status == AgentTask.DONE
    assert task.finished_at is not None
    assert task.error_message == ""


@pytest.mark.django_db
def test_analytics_agent_openai_exception_ends_error():
    from agents.agents.analytics import AnalyticsAgent

    with patch(
        "agents.agents._openai_cache.get_openai_client",
        side_effect=RuntimeError("openai down"),
    ), patch("agents.agents.analytics.send_telegram"):
        task = AnalyticsAgent().run()

    task.refresh_from_db()
    assert task.status == AgentTask.ERROR
    assert "openai down" in task.error_message
    assert task.finished_at is not None


@pytest.mark.django_db
def test_analytics_agent_orphan_running_cleaned_up_by_finally():
    """
    Эмулируем ситуацию: except-блок упал на save(ERROR).
    finally с ensure_task_finalized должен всё равно пометить таску ERROR.
    """
    from agents.agents.analytics import AnalyticsAgent

    # gather_data падает — агент идёт в except
    # Подменяем AgentTask.save так, чтобы он молча ничего не делал внутри except,
    # оставляя status=RUNNING в БД. finally должен это починить.
    original_save = AgentTask.save
    call_count = {"n": 0}

    def flaky_save(self, *args, **kwargs):
        call_count["n"] += 1
        # Внутри except блока агент вызывает save с update_fields, содержащим "status".
        # Первый такой вызов — делаем no-op (эмулируем сбой записи).
        if (
            kwargs.get("update_fields")
            and "status" in kwargs["update_fields"]
            and self.status == AgentTask.ERROR
            and call_count["n"] <= 2
        ):
            return  # молча ничего не записали — в БД всё ещё RUNNING
        return original_save(self, *args, **kwargs)

    with patch.object(
        AnalyticsAgent, "gather_data", side_effect=RuntimeError("boom")
    ), patch.object(AgentTask, "save", flaky_save), \
         patch("agents.agents.analytics.send_telegram"):
        task = AnalyticsAgent().run()

    task.refresh_from_db()
    assert task.status == AgentTask.ERROR
    # Сообщение от страховки, а не от исходного исключения —
    # потому что save(ERROR) был no-op
    assert task.error_message == "Agent exited без финализации"
    assert task.finished_at is not None


# ──────────────────── OfferAgent ────────────────────

@pytest.mark.django_db
def test_offer_agent_exception_ends_error():
    from agents.agents.offers import OfferAgent

    with patch(
        "agents.agents._openai_cache.get_openai_client",
        side_effect=RuntimeError("api fail"),
    ), patch("agents.agents.offers.send_telegram"):
        task = OfferAgent().run()

    task.refresh_from_db()
    assert task.status == AgentTask.ERROR
    assert "api fail" in task.error_message


@pytest.mark.django_db
def test_offer_agent_success_ends_done():
    import json as _json
    from agents.agents.offers import OfferAgent

    offer_json = _json.dumps({
        "offers": [{"title": "Акция -20% на массаж", "description": "Скидка",
                    "discount_pct": 20, "target_audience": "Все", "duration_days": 7}]
    })
    fake_openai = MagicMock()
    fake_openai.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=offer_json))]
    )

    with patch("agents.agents._openai_cache.get_openai_client", return_value=fake_openai), \
         patch("agents.agents.offers.send_telegram"):
        task = OfferAgent().run()

    task.refresh_from_db()
    assert task.status == AgentTask.DONE
    assert task.finished_at is not None
