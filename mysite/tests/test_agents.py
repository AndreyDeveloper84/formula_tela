"""
Тесты для AI-агентов.
Все вызовы OpenAI замоканы — реальные API-запросы не делаются.
"""
import pytest
from unittest.mock import MagicMock, patch

from model_bakery import baker


# ──────────────────────────────────────────────
# Данные и метрики
# ──────────────────────────────────────────────

@pytest.mark.django_db
def test_analytics_gather_data_counts():
    """gather_data считает заявки за неделю корректно."""
    baker.make("services_app.BookingRequest", service_name="Маникюр", is_processed=True)
    baker.make("services_app.BookingRequest", service_name="Маникюр", is_processed=False)
    baker.make("services_app.BookingRequest", service_name="Педикюр", is_processed=False)

    from agents.agents.analytics import AnalyticsAgent

    data = AnalyticsAgent().gather_data()
    assert data["total_requests"] >= 3
    assert data["processed"] >= 1
    assert data["unprocessed"] >= 2
    assert any(name == "Маникюр" for name, _ in data["top_services"])


@pytest.mark.django_db
def test_offer_gather_data_returns_structure():
    """gather_data для OfferAgent возвращает ожидаемую структуру."""
    from agents.agents.offers import OfferAgent

    data = OfferAgent().gather_data()
    assert "low_demand_services" in data
    assert "active_promotions" in data
    assert "active_masters" in data


# ──────────────────────────────────────────────
# AnalyticsAgent.run()
# ──────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.agents.analytics.send_telegram", return_value=True)
@patch("agents.agents.analytics.get_openai_client")
def test_analytics_agent_run_done(mock_openai_cls, mock_tg):
    """Агент завершается со статусом DONE и создаёт AgentReport."""
    mock_openai_cls.return_value.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Всё хорошо, 3 заявки за неделю."))]
    )

    from agents.agents.analytics import AnalyticsAgent
    from agents.models import AgentTask

    task = AnalyticsAgent().run()

    assert task.status == AgentTask.DONE
    assert task.report.summary == "Всё хорошо, 3 заявки за неделю."
    assert mock_tg.called


@pytest.mark.django_db
@patch("agents.agents.analytics.get_openai_client")
def test_analytics_agent_run_error(mock_openai_cls):
    """Если OpenAI бросает исключение — статус ERROR, задача сохранена."""
    mock_openai_cls.return_value.chat.completions.create.side_effect = RuntimeError("quota exceeded")

    from agents.agents.analytics import AnalyticsAgent
    from agents.models import AgentTask

    task = AnalyticsAgent().run()

    assert task.status == AgentTask.ERROR
    assert "quota exceeded" in task.error_message


# ──────────────────────────────────────────────
# OfferAgent.run()
# ──────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.agents.offers.send_telegram", return_value=True)
@patch("agents.agents.offers.get_openai_client")
def test_offer_agent_run_done(mock_openai_cls, mock_tg):
    """OfferAgent завершается со статусом DONE и создаёт AgentReport."""
    mock_openai_cls.return_value.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Предлагаю акцию -20% на маникюр."))]
    )

    from agents.agents.offers import OfferAgent
    from agents.models import AgentTask

    task = OfferAgent().run()

    assert task.status == AgentTask.DONE
    assert task.report.summary == "Предлагаю акцию -20% на маникюр."


# ──────────────────────────────────────────────
# SupervisorAgent
# ──────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.agents.supervisor.get_openai_client")
def test_supervisor_decide_analytics(mock_openai_cls):
    """Supervisor возвращает ['analytics'] если GPT так решил."""
    mock_openai_cls.return_value.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"agents": ["analytics"]}'))]
    )

    from agents.agents.supervisor import SupervisorAgent

    decision = SupervisorAgent().decide()
    assert "analytics" in decision


@pytest.mark.django_db
@patch("agents.agents.supervisor.get_openai_client")
def test_supervisor_decide_both(mock_openai_cls):
    """Supervisor возвращает оба агента."""
    mock_openai_cls.return_value.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content='{"agents": ["analytics", "offers"]}'))]
    )

    from agents.agents.supervisor import SupervisorAgent

    decision = SupervisorAgent().decide()
    assert set(decision) == {"analytics", "offers"}


@pytest.mark.django_db
@patch("agents.agents.supervisor.get_openai_client")
def test_supervisor_fallback_on_error(mock_openai_cls):
    """При ошибке GPT Supervisor возвращает fallback=['analytics']."""
    mock_openai_cls.return_value.chat.completions.create.side_effect = RuntimeError("network error")

    from agents.agents.supervisor import SupervisorAgent

    decision = SupervisorAgent().decide()
    assert decision == ["analytics"]


# ──────────────────────────────────────────────
# DailyMetric сохраняется
# ──────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.agents.analytics.send_telegram", return_value=False)
@patch("agents.agents.analytics.get_openai_client")
def test_daily_metric_created(mock_openai_cls, _mock_tg):
    """После запуска AnalyticsAgent создаётся запись DailyMetric."""
    mock_openai_cls.return_value.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Метрика сохранена."))]
    )
    baker.make("services_app.BookingRequest", service_name="Массаж", is_processed=True)

    from agents.agents.analytics import AnalyticsAgent
    from agents.models import DailyMetric

    AnalyticsAgent().run()

    import datetime
    assert DailyMetric.objects.filter(date=datetime.date.today()).exists()
