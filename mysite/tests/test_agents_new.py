"""
Тесты для 4 новых AI-агентов и SupervisorAgent.weekly_run().
Все тесты используют моки — реальные OpenAI/YClients/Yandex API не вызываются.
"""
import datetime
import json
import pytest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from model_bakery import baker


# ─── helpers ────────────────────────────────────────────────────────────────

def _make_openai_mock(content: str):
    """Создаёт mock OpenAI клиента с фиксированным ответом."""
    mock = MagicMock()
    mock.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=content))]
    )
    return mock


OFFER_JSON = json.dumps({"hypotheses": [
    {
        "title": "Антицеллюлитный марафон",
        "segment": "problem_zones",
        "pain": "Целлюлит не уходит",
        "solution": "LPG 5 процедур",
        "proof": "87% клиенток видят результат",
        "cta": "Записаться на замер",
        "social_text": "Устала от апельсиновой корки?..",
        "landing_brief": "H1: Избавься от целлюлита за 5 сеансов",
        "predicted_cr_lift": "+12%",
    },
    {
        "title": "Первый визит со скидкой",
        "segment": "new",
        "pain": "Страшно идти в новый салон",
        "solution": "Скидка 20% на первую процедуру",
        "proof": "4.9★ на Яндекс.Картах",
        "cta": "Записаться",
        "social_text": "Попробуй наш салон...",
        "landing_brief": "Добавить блок 'Первый визит'",
        "predicted_cr_lift": "+20%",
    },
]})

SEO_JSON = json.dumps({
    "pages": [
        {"slug": "massazh", "score": 2, "missing_blocks": ["faq", "price_table"],
         "recommendations": ["Добавить FAQ", "Добавить цены"]},
        {"slug": "laser", "score": 4, "missing_blocks": [],
         "recommendations": ["Обновить H1"]},
    ],
    "critical_count": 1,
    "summary": "2 страницы требуют доработки",
})

SMM_JSON = json.dumps({"posts": [
    {"day_of_week": i % 7, "platform": p, "post_type": "post",
     "theme": f"Тема {i}", "description": f"Описание {i}",
     "hashtags": "#салон", "cta": "Записаться"}
    for i, p in enumerate(
        ["vk", "instagram", "telegram"] * 7  # 21 пост
    )
]})

BUDGET_JSON = json.dumps({
    "funnel": {"impressions": "12000", "clicks": "340", "leads": "42",
               "bookings": "28", "visits": "21", "revenue": "189000"},
    "leaks": [{"stage": "клики→лид", "problem": "CTR формы 12%", "impact": "высокий"}],
    "actions": [{"priority": 1, "type": "ux", "description": "Pop-up оффер",
                 "expected_result": "+8% лидов"}],
})


# ─── OfferPackagesAgent ──────────────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.agents.offer_packages.send_telegram", return_value=True)
@patch("agents.agents.offer_packages.OpenAI")
def test_offer_packages_agent_done(mock_openai_cls, mock_tg):
    mock_openai_cls.return_value = _make_openai_mock(OFFER_JSON)
    from agents.agents.offer_packages import OfferPackagesAgent
    from agents.models import AgentReport, AgentTask
    task = OfferPackagesAgent().run()
    assert task.status == AgentTask.DONE
    report = AgentReport.objects.get(task=task)
    assert len(report.recommendations) == 2
    assert report.recommendations[0]["title"] == "Антицеллюлитный марафон"
    mock_tg.assert_called_once()


@pytest.mark.django_db
@patch("agents.agents.offer_packages.send_telegram", return_value=True)
@patch("agents.agents.offer_packages.OpenAI")
def test_offer_packages_agent_with_booking_data(mock_openai_cls, mock_tg):
    """gather_data подбирает BookingRequest и Service."""
    baker.make("services_app.Service", is_active=True, name="LPG массаж")
    baker.make("services_app.BookingRequest", service_name="LPG массаж", is_processed=True)
    mock_openai_cls.return_value = _make_openai_mock(OFFER_JSON)
    from agents.agents.offer_packages import OfferPackagesAgent
    from agents.models import AgentTask
    task = OfferPackagesAgent().run()
    assert task.status == AgentTask.DONE
    assert "LPG массаж" in str(task.input_context)


@pytest.mark.django_db
@patch("agents.agents.offer_packages.send_telegram", return_value=True)
@patch("agents.agents.offer_packages.OpenAI")
def test_offer_packages_agent_error_saved(mock_openai_cls, mock_tg):
    """При ошибке OpenAI статус = ERROR."""
    mock_openai_cls.return_value.chat.completions.create.side_effect = RuntimeError("API down")
    from agents.agents.offer_packages import OfferPackagesAgent
    from agents.models import AgentTask
    task = OfferPackagesAgent().run()
    assert task.status == AgentTask.ERROR
    assert "API down" in task.error_message


# ─── SEOLandingAgent ─────────────────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.agents.seo_landing.send_telegram", return_value=True)
@patch("agents.agents.seo_landing.OpenAI")
def test_seo_landing_agent_done(mock_openai_cls, mock_tg):
    mock_openai_cls.return_value = _make_openai_mock(SEO_JSON)
    baker.make("services_app.Service", is_active=True, slug="massazh", name="Массаж")
    from agents.agents.seo_landing import SEOLandingAgent
    from agents.models import AgentReport, AgentTask
    task = SEOLandingAgent().run()
    assert task.status == AgentTask.DONE
    report = AgentReport.objects.get(task=task)
    assert report.summary == "2 страницы требуют доработки"
    mock_tg.assert_called_once()


@pytest.mark.django_db
def test_seo_landing_gather_data_empty_service():
    """Service без блоков → попадает в empty_pages."""
    svc = baker.make("services_app.Service", is_active=True, slug="test-empty-svc")
    from agents.agents.seo_landing import SEOLandingAgent
    data = SEOLandingAgent().gather_data()
    assert "test-empty-svc" in data["empty_pages"]


@pytest.mark.django_db
def test_seo_landing_gather_data_missing_blocks():
    """Service без faq-блока → missing_required_blocks содержит 'faq'."""
    svc = baker.make("services_app.Service", is_active=True, slug="no-faq")
    baker.make("services_app.ServiceBlock", service=svc, block_type="text", is_active=True)
    from agents.agents.seo_landing import SEOLandingAgent
    data = SEOLandingAgent().gather_data()
    page = next((p for p in data["pages"] if p["slug"] == "no-faq"), None)
    assert page is not None
    assert "faq" in page["missing_required_blocks"]


@pytest.mark.django_db
@patch("agents.agents.seo_landing.send_telegram", return_value=True)
@patch("agents.agents.seo_landing.OpenAI")
def test_seo_landing_agent_error_saved(mock_openai_cls, mock_tg):
    mock_openai_cls.return_value.chat.completions.create.side_effect = RuntimeError("GPT error")
    from agents.agents.seo_landing import SEOLandingAgent
    from agents.models import AgentTask
    task = SEOLandingAgent().run()
    assert task.status == AgentTask.ERROR
    assert "GPT error" in task.error_message


# ─── SMMGrowthAgent ──────────────────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.agents.smm_growth.send_telegram", return_value=True)
@patch("agents.agents.smm_growth.OpenAI")
def test_smm_growth_saves_content_plan(mock_openai_cls, mock_tg):
    """SMMGrowthAgent создаёт 21 запись ContentPlan."""
    mock_openai_cls.return_value = _make_openai_mock(SMM_JSON)
    from agents.agents.smm_growth import SMMGrowthAgent
    from agents.models import AgentTask, ContentPlan
    task = SMMGrowthAgent().run()
    assert task.status == AgentTask.DONE
    assert ContentPlan.objects.filter(created_by_task=task).count() == 21
    mock_tg.assert_called_once()


@pytest.mark.django_db
@patch("agents.agents.smm_growth.send_telegram", return_value=True)
@patch("agents.agents.smm_growth.OpenAI")
def test_smm_growth_uses_offer_packages_report(mock_openai_cls, mock_tg):
    """gather_data подхватывает последний OfferPackages отчёт."""
    mock_openai_cls.return_value = _make_openai_mock(SMM_JSON)
    # Создаём существующий OfferPackages отчёт
    from agents.models import AgentReport, AgentTask
    parent_task = baker.make(AgentTask, agent_type=AgentTask.OFFER_PACKAGES, status=AgentTask.DONE)
    baker.make(AgentReport, task=parent_task, recommendations=[{"title": "Акция 1"}])
    from agents.agents.smm_growth import SMMGrowthAgent
    agent = SMMGrowthAgent()
    data = agent.gather_data()
    assert len(data["offer_hypotheses"]) > 0
    assert data["offer_hypotheses"][0]["title"] == "Акция 1"


@pytest.mark.django_db
@patch("agents.agents.smm_growth.send_telegram", return_value=True)
@patch("agents.agents.smm_growth.OpenAI")
def test_smm_growth_invalid_platform_fallback(mock_openai_cls, mock_tg):
    """Некорректная платформа в ответе GPT → заменяется на 'telegram'."""
    posts_json = json.dumps({"posts": [
        {"day_of_week": 0, "platform": "INVALID", "post_type": "post",
         "theme": "Тест", "description": "Текст", "hashtags": "#тест", "cta": "Записаться"}
    ]})
    mock_openai_cls.return_value = _make_openai_mock(posts_json)
    from agents.agents.smm_growth import SMMGrowthAgent
    from agents.models import AgentTask, ContentPlan
    task = SMMGrowthAgent().run()
    assert task.status == AgentTask.DONE
    post = ContentPlan.objects.filter(created_by_task=task).first()
    assert post is not None
    assert post.platform == "telegram"


@pytest.mark.django_db
@patch("agents.agents.smm_growth.send_telegram", return_value=True)
@patch("agents.agents.smm_growth.OpenAI")
def test_smm_growth_agent_error_saved(mock_openai_cls, mock_tg):
    mock_openai_cls.return_value.chat.completions.create.side_effect = RuntimeError("GPT fail")
    from agents.agents.smm_growth import SMMGrowthAgent
    from agents.models import AgentTask
    task = SMMGrowthAgent().run()
    assert task.status == AgentTask.ERROR


# ─── AnalyticsBudgetAgent ────────────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.agents.analytics_budget.send_telegram", return_value=True)
@patch("agents.agents.analytics_budget.OpenAI")
def test_analytics_budget_agent_done(mock_openai_cls, mock_tg):
    """Агент завершается DONE, отчёт создаётся."""
    mock_openai_cls.return_value = _make_openai_mock(BUDGET_JSON)
    from agents.agents.analytics_budget import AnalyticsBudgetAgent
    from agents.models import AgentReport, AgentTask
    task = AnalyticsBudgetAgent().run()
    assert task.status == AgentTask.DONE
    report = AgentReport.objects.get(task=task)
    assert "Утечек" in report.summary
    mock_tg.assert_called_once()


@pytest.mark.django_db
@patch("agents.agents.analytics_budget.send_telegram", return_value=True)
@patch("agents.agents.analytics_budget.OpenAI")
def test_analytics_budget_graceful_without_yandex(mock_openai_cls, mock_tg, settings):
    """Агент работает нормально, если Метрика/Директ/VK не настроены."""
    settings.YANDEX_METRIKA_TOKEN = ""
    settings.YANDEX_DIRECT_TOKEN = ""
    settings.VK_ADS_TOKEN = ""
    settings.VK_ADS_ACCOUNT_ID = ""
    mock_openai_cls.return_value = _make_openai_mock(BUDGET_JSON)
    from agents.agents.analytics_budget import AnalyticsBudgetAgent
    from agents.models import AgentTask
    task = AnalyticsBudgetAgent().run()
    # Должен завершиться успешно (graceful degradation)
    assert task.status == AgentTask.DONE


@pytest.mark.django_db
@patch("agents.agents.analytics_budget.send_telegram", return_value=True)
@patch("agents.agents.analytics_budget.OpenAI")
@patch("agents.integrations.vk_ads.requests.request")
def test_analytics_budget_vk_data_in_context(mock_vk_req, mock_openai_cls, mock_tg, settings):
    """VK-данные появляются в input_context с префиксом vk_."""
    # Настраиваем VK-токены
    settings.VK_ADS_TOKEN = "tok"
    settings.VK_ADS_ACCOUNT_ID = "99"
    # 1-й вызов: listing планов
    plans_resp = MagicMock(ok=True, json=lambda: {
        "items": [{"id": 101, "name": "Тест-кампания"}], "count": 1,
    })
    # 2-й вызов: статистика
    stats_resp = MagicMock(ok=True, json=lambda: {
        "items": [{"id": 101, "rows": [
            {"date": "2026-01-15",
             "base": {"clicks": 77, "shows": 3000, "spent": 5500.0}},
        ]}]
    })
    mock_vk_req.side_effect = [plans_resp, stats_resp]
    mock_openai_cls.return_value = _make_openai_mock(BUDGET_JSON)

    from agents.agents.analytics_budget import AnalyticsBudgetAgent
    from agents.models import AgentTask
    task = AnalyticsBudgetAgent().run()

    assert task.status == AgentTask.DONE
    assert task.input_context.get("vk_clicks") == 77
    assert task.input_context.get("vk_impressions") == 3000
    assert task.input_context.get("vk_cost") == 5500.0
    assert "vk_campaigns_count" in task.input_context


@pytest.mark.django_db
@patch("agents.agents.analytics_budget.send_telegram", return_value=True)
@patch("agents.agents.analytics_budget.OpenAI")
def test_analytics_budget_uses_booking_requests(mock_openai_cls, mock_tg):
    """gather_data правильно считает лиды из BookingRequest."""
    mock_openai_cls.return_value = _make_openai_mock(BUDGET_JSON)
    baker.make("services_app.BookingRequest", is_processed=True, _quantity=3)
    baker.make("services_app.BookingRequest", is_processed=False, _quantity=2)
    from agents.agents.analytics_budget import AnalyticsBudgetAgent
    agent = AnalyticsBudgetAgent()
    data = agent.gather_data()
    assert data["leads_total"] >= 5
    assert data["leads_processed"] >= 3


@pytest.mark.django_db
@patch("agents.agents.analytics_budget.send_telegram", return_value=True)
@patch("agents.agents.analytics_budget.OpenAI")
def test_analytics_budget_error_saved(mock_openai_cls, mock_tg):
    mock_openai_cls.return_value.chat.completions.create.side_effect = RuntimeError("err")
    from agents.agents.analytics_budget import AnalyticsBudgetAgent
    from agents.models import AgentTask
    task = AnalyticsBudgetAgent().run()
    assert task.status == AgentTask.ERROR


# ─── SupervisorAgent.weekly_run() ────────────────────────────────────────────

@pytest.mark.django_db
@patch("agents.telegram.send_telegram", return_value=True)  # патчим источник (local import в weekly_run)
@patch("agents.agents.supervisor.OpenAI")
def test_supervisor_weekly_run_sends_telegram(mock_openai_cls, mock_tg):
    """weekly_run отправляет бэклог в Telegram."""
    mock_openai_cls.return_value.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Бэклог на неделю:\n1. Запустить акцию"))]
    )
    from agents.agents.supervisor import SupervisorAgent
    SupervisorAgent().weekly_run()
    mock_tg.assert_called_once()
    call_text = mock_tg.call_args[0][0]
    assert "бэклог" in call_text.lower()


@pytest.mark.django_db
@patch("agents.telegram.send_telegram", return_value=True)
@patch("agents.agents.supervisor.OpenAI")
def test_supervisor_weekly_run_collects_all_reports(mock_openai_cls, mock_tg):
    """weekly_run собирает отчёты от всех 6 типов агентов."""
    mock_openai_cls.return_value.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Бэклог"))]
    )
    from agents.models import AgentReport, AgentTask

    # Создаём отчёты для нескольких агентов
    for atype in [AgentTask.ANALYTICS, AgentTask.OFFER_PACKAGES, AgentTask.SEO_LANDING]:
        t = baker.make(AgentTask, agent_type=atype, status=AgentTask.DONE)
        baker.make(AgentReport, task=t, summary=f"Резюме {atype}", recommendations=[])

    from agents.agents.supervisor import SupervisorAgent
    SupervisorAgent().weekly_run()

    prompt_used = mock_openai_cls.return_value.chat.completions.create.call_args[1]["messages"][1]["content"]
    assert "Аналитика" in prompt_used
    assert "Пакеты" in prompt_used
    assert "SEO" in prompt_used


@pytest.mark.django_db
@patch("agents.telegram.send_telegram", return_value=True)
@patch("agents.agents.supervisor.OpenAI")
def test_supervisor_weekly_run_handles_openai_error(mock_openai_cls, mock_tg):
    """Ошибка OpenAI в weekly_run не роняет процесс."""
    mock_openai_cls.return_value.chat.completions.create.side_effect = RuntimeError("GPT down")
    from agents.agents.supervisor import SupervisorAgent
    # Не должно поднимать исключение
    SupervisorAgent().weekly_run()
    mock_tg.assert_not_called()
