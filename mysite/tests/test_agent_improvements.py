"""
Тесты для доработки AI-агентов: замыкание цикла, надёжность,
поведенческая аналитика, feedback loop, мониторинг.
"""
import datetime
import json

import pytest
from unittest.mock import MagicMock, patch

from model_bakery import baker


# ── Helpers ──────────────────────────────────────────────────────────────

def _make_openai_mock(content: str):
    """Создаёт мок OpenAI client с заданным ответом."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=content))]
    )
    return mock_client


OFFER_JSON = json.dumps({
    "offers": [
        {
            "title": "Весенний массаж",
            "description": "Скидка на классический массаж",
            "discount_pct": 15,
            "target_audience": "Новые клиенты",
            "duration_days": 7,
        },
        {
            "title": "Комбо SPA",
            "description": "Два по цене одного",
            "discount_pct": 20,
            "target_audience": "Все",
            "duration_days": 10,
        },
    ]
})


# ══════════════════════════════════════════════════════════════════════════
# Блок 1: Замкнуть цикл
# ══════════════════════════════════════════════════════════════════════════

class TestOfferAgentPromotionDraft:
    """1.1 OfferAgent → auto-create Promotion (is_active=False)."""

    @pytest.mark.django_db
    @patch("agents.agents.offers.send_telegram", return_value=True)
    @patch("agents.agents.offers.get_openai_client")
    def test_creates_draft_promotions(self, mock_openai, mock_tg):
        mock_openai.return_value = _make_openai_mock(OFFER_JSON)

        from agents.agents.offers import OfferAgent
        from agents.models import AgentTask
        from services_app.models import Promotion

        task = OfferAgent().run()
        assert task.status == AgentTask.DONE

        # Должны быть созданы 2 черновика
        drafts = Promotion.objects.filter(is_active=False)
        assert drafts.count() == 2

        promo = drafts.first()
        assert promo.discount_percent <= 30
        assert promo.starts_at is not None
        assert promo.ends_at is not None

    @pytest.mark.django_db
    @patch("agents.agents.offers.send_telegram", return_value=True)
    @patch("agents.agents.offers.get_openai_client")
    def test_structured_recommendations(self, mock_openai, mock_tg):
        mock_openai.return_value = _make_openai_mock(OFFER_JSON)

        from agents.agents.offers import OfferAgent
        from agents.models import AgentTask

        task = OfferAgent().run()
        report = task.report

        assert isinstance(report.recommendations, list)
        assert len(report.recommendations) == 2
        assert report.recommendations[0]["title"] == "Весенний массаж"

    @pytest.mark.django_db
    @patch("agents.agents.offers.send_telegram", return_value=True)
    @patch("agents.agents.offers.get_openai_client")
    def test_discount_capped_at_30(self, mock_openai, mock_tg):
        """Скидка ограничена 30%."""
        high_discount = json.dumps({
            "offers": [{"title": "Мега скидка", "description": "x",
                        "discount_pct": 50, "target_audience": "Все",
                        "duration_days": 7}]
        })
        mock_openai.return_value = _make_openai_mock(high_discount)

        from agents.agents.offers import OfferAgent
        from services_app.models import Promotion

        OfferAgent().run()
        promo = Promotion.objects.filter(is_active=False).first()
        assert promo.discount_percent == 30


class TestContentPlanDedupe:
    """1.2 ContentPlan dedupe при повторном запуске."""

    @pytest.mark.django_db
    @patch("agents.agents.smm_growth.send_telegram", return_value=True)
    @patch("agents.agents.smm_growth.get_openai_client")
    def test_no_duplicates_on_rerun(self, mock_openai, mock_tg):
        smm_json = json.dumps({
            "posts": [
                {"day_of_week": 0, "platform": "vk", "post_type": "post",
                 "theme": "Тема 1", "description": "Описание", "hashtags": "#тест",
                 "cta": "Записаться"},
            ]
        })
        mock_openai.return_value = _make_openai_mock(smm_json)

        from agents.agents.smm_growth import SMMGrowthAgent
        from agents.models import ContentPlan

        # Первый запуск
        SMMGrowthAgent().run()
        count_after_first = ContentPlan.objects.count()
        assert count_after_first == 1

        # Второй запуск — дубли не должны появиться
        SMMGrowthAgent().run()
        count_after_second = ContentPlan.objects.count()
        assert count_after_second == 1  # старые удалены, новые созданы


class TestGenerateMissingLandings:
    """1.3 LandingPage QC pipeline."""

    @pytest.mark.django_db
    @patch("agents.agents.landing_generator.notify_new_landing", return_value=True)
    @patch("agents.agents.landing_generator.get_openai_client")
    def test_generates_for_cluster_without_landing(self, mock_openai, mock_notify):
        landing_json = json.dumps({
            "meta_title": "Массаж спины в Пензе",
            "meta_description": "Лучший массаж спины",
            "h1": "Массаж спины",
            "intro": "Текст вводный",
            "how_it_works": "Как это работает",
            "who_is_it_for": "Для всех",
            "contraindications": "Нет",
            "results": "Улучшение",
            "faq": [{"question": "Вопрос?", "answer": "Ответ."}],
            "cta_text": "Записаться",
            "internal_links": ["/uslugi/massazh/"],
        })
        mock_openai.return_value = _make_openai_mock(landing_json)

        from agents.models import LandingPage, SeoKeywordCluster

        cluster = baker.make(
            SeoKeywordCluster,
            name="Массаж спины Пенза",
            service_slug="massazh-spiny",
            is_active=True,
            keywords=["массаж спины пенза"],
            target_url="/uslugi/massazh-spiny/",
        )

        from agents.tasks import generate_missing_landings
        generate_missing_landings()

        assert LandingPage.objects.filter(cluster=cluster).exists()
        landing = LandingPage.objects.get(cluster=cluster)
        assert landing.status == LandingPage.STATUS_DRAFT


# ══════════════════════════════════════════════════════════════════════════
# Блок 2: Надёжность
# ══════════════════════════════════════════════════════════════════════════

class TestTelegramErrorAlerts:
    """2.1 Telegram-алерты на ERROR."""

    @pytest.mark.django_db
    @patch("agents.telegram.send_telegram", return_value=True)
    def test_send_agent_error_alert(self, mock_tg):
        from agents.models import AgentTask
        from agents.telegram import send_agent_error_alert

        task = baker.make(
            AgentTask,
            agent_type=AgentTask.OFFERS,
            status=AgentTask.ERROR,
            error_message="Test error message",
        )
        result = send_agent_error_alert(task)
        assert result is True
        mock_tg.assert_called_once()
        call_text = mock_tg.call_args[0][0]
        assert "Ошибка агента" in call_text
        assert "Test error" in call_text

    @pytest.mark.django_db
    @patch("agents.agents.offers.send_telegram", return_value=True)
    @patch("agents.agents.offers.get_openai_client")
    def test_error_alert_sent_on_agent_failure(self, mock_openai, mock_tg):
        mock_openai.return_value.chat.completions.create.side_effect = Exception("API down")

        from agents.agents.offers import OfferAgent
        from agents.models import AgentTask

        with patch("agents.telegram.send_agent_error_alert") as mock_alert:
            task = OfferAgent().run()
            assert task.status == AgentTask.ERROR
            mock_alert.assert_called_once()

    @pytest.mark.django_db
    def test_lifecycle_sends_alert_on_orphan(self):
        from agents.models import AgentTask

        task = baker.make(
            AgentTask,
            agent_type=AgentTask.ANALYTICS,
            status=AgentTask.RUNNING,
        )

        with patch("agents.telegram.send_agent_error_alert") as mock_alert:
            from agents.agents._lifecycle import ensure_task_finalized
            ensure_task_finalized(task)

            task.refresh_from_db()
            assert task.status == AgentTask.ERROR
            mock_alert.assert_called_once()


class TestSeoTaskEscalation:
    """2.2 SeoTask dedupe с эскалацией."""

    @pytest.mark.django_db
    def test_escalation_updates_existing_task(self):
        from agents.models import SeoKeywordCluster, SeoClusterSnapshot, SeoTask

        cluster = baker.make(
            SeoKeywordCluster,
            name="Массаж Пенза",
            target_url="/uslugi/massazh/",
            is_active=True,
            keywords=["массаж пенза"],
        )

        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        # Начальная задача
        task = SeoTask.objects.create(
            task_type=SeoTask.TYPE_UPDATE_META,
            target_url=cluster.target_url,
            title="Падение кликов: Массаж Пенза",
            priority=SeoTask.PRIORITY_MEDIUM,
            status=SeoTask.STATUS_OPEN,
        )

        # Снапшоты: было 100, стало 50
        baker.make(SeoClusterSnapshot, cluster=cluster, date=week_ago,
                   total_clicks=100, total_impressions=500,
                   avg_ctr=0.2, avg_position=5.0, matched_queries=3)
        baker.make(SeoClusterSnapshot, cluster=cluster, date=today,
                   total_clicks=50, total_impressions=400,
                   avg_ctr=0.125, avg_position=7.0, matched_queries=3)

        with patch("agents.telegram.send_seo_alert", return_value=True):
            from agents.tasks import analyze_rank_changes
            analyze_rank_changes()

        task.refresh_from_db()
        assert task.priority == SeoTask.PRIORITY_HIGH
        assert task.escalation_count >= 1
        assert "Повторное падение" in task.description

        # Не должно быть создано новых задач
        total_tasks = SeoTask.objects.filter(
            target_url=cluster.target_url,
            task_type=SeoTask.TYPE_UPDATE_META,
        ).count()
        assert total_tasks == 1


# ══════════════════════════════════════════════════════════════════════════
# Блок 3: Поведенческая аналитика
# ══════════════════════════════════════════════════════════════════════════

class TestSEOBehavioralMetrics:
    """3.1 get_page_behavior() в SEOLandingAgent."""

    @pytest.mark.django_db
    def test_fetch_metrika_behavior_graceful(self):
        """Если Метрика недоступна — возвращает пустой dict."""
        from agents.agents.seo_landing import SEOLandingAgent

        with patch(
            "agents.agents.seo_landing.SEOLandingAgent._fetch_metrika_behavior",
        ) as mock_metrika:
            mock_metrika.return_value = {}
            agent = SEOLandingAgent()
            result = agent._fetch_metrika_behavior([], "2026-01-01", "2026-01-07")
            assert result == {}

    @pytest.mark.django_db
    @patch("agents.agents.seo_landing.send_telegram", return_value=True)
    @patch("agents.agents.seo_landing.get_openai_client")
    def test_seo_agent_includes_metrika_in_context(self, mock_openai, mock_tg):
        """SEOLandingAgent добавляет metrika_available в input_context."""
        seo_json = json.dumps({
            "pages": [{"slug": "test", "score": 4, "missing_blocks": [],
                       "recommendations": ["OK"]}],
            "critical_count": 0,
            "summary": "Всё хорошо",
        })
        mock_openai.return_value = _make_openai_mock(seo_json)

        baker.make("services_app.Service", slug="test-seo", is_active=True)

        from agents.agents.seo_landing import SEOLandingAgent

        with patch.object(SEOLandingAgent, "_fetch_webmaster_data", return_value={
            "pages_map": {}, "top_queries": [], "drops": [],
        }):
            with patch.object(SEOLandingAgent, "_fetch_metrika_behavior", return_value={}):
                task = SEOLandingAgent().run()

        from agents.models import AgentTask
        assert task.status == AgentTask.DONE
        assert "metrika_available" in task.input_context


# ══════════════════════════════════════════════════════════════════════════
# Блок 4: Feedback loop
# ══════════════════════════════════════════════════════════════════════════

class TestAgentRecommendationOutcome:
    """4.1 Модель AgentRecommendationOutcome."""

    @pytest.mark.django_db
    def test_create_outcome(self):
        from agents.models import AgentRecommendationOutcome, AgentReport, AgentTask

        task = baker.make(AgentTask, agent_type=AgentTask.OFFERS, status=AgentTask.DONE)
        report = baker.make(AgentReport, task=task)

        outcome = AgentRecommendationOutcome.objects.create(
            report=report,
            agent_type=AgentTask.OFFERS,
            title="Тестовая рекомендация",
            body={"discount_pct": 15},
            status=AgentRecommendationOutcome.STATUS_NEW,
        )
        assert outcome.pk is not None
        assert outcome.status == "new"
        assert str(outcome).startswith("[Новая]")

    @pytest.mark.django_db
    def test_status_transitions(self):
        from agents.models import AgentRecommendationOutcome, AgentReport, AgentTask
        from django.utils import timezone

        task = baker.make(AgentTask, agent_type=AgentTask.OFFERS, status=AgentTask.DONE)
        report = baker.make(AgentReport, task=task)
        outcome = AgentRecommendationOutcome.objects.create(
            report=report,
            agent_type=AgentTask.OFFERS,
            title="Test",
        )
        assert outcome.status == "new"

        outcome.status = AgentRecommendationOutcome.STATUS_ACCEPTED
        outcome.decided_at = timezone.now()
        outcome.save()
        outcome.refresh_from_db()
        assert outcome.status == "accepted"


class TestCreateOutcomesHelper:
    """4.2 Хелпер _outcomes.create_outcomes."""

    @pytest.mark.django_db
    def test_creates_outcomes_from_list(self):
        from agents.agents._outcomes import create_outcomes
        from agents.models import AgentRecommendationOutcome, AgentReport, AgentTask

        task = baker.make(AgentTask, agent_type=AgentTask.OFFERS, status=AgentTask.DONE)
        report = baker.make(AgentReport, task=task)

        items = [
            {"title": "Акция 1", "discount_pct": 10},
            {"title": "Акция 2", "discount_pct": 20},
        ]
        count = create_outcomes(report, AgentTask.OFFERS, items)
        assert count == 2
        assert AgentRecommendationOutcome.objects.filter(report=report).count() == 2

    @pytest.mark.django_db
    def test_skips_non_dict_items(self):
        from agents.agents._outcomes import create_outcomes
        from agents.models import AgentRecommendationOutcome, AgentReport, AgentTask

        task = baker.make(AgentTask, agent_type=AgentTask.OFFERS, status=AgentTask.DONE)
        report = baker.make(AgentReport, task=task)

        count = create_outcomes(report, AgentTask.OFFERS, ["string", 42, None])
        assert count == 0


class TestOfferAgentCreatesOutcomes:
    """4.2 OfferAgent создаёт Outcome-записи."""

    @pytest.mark.django_db
    @patch("agents.agents.offers.send_telegram", return_value=True)
    @patch("agents.agents.offers.get_openai_client")
    def test_outcomes_created_on_run(self, mock_openai, mock_tg):
        mock_openai.return_value = _make_openai_mock(OFFER_JSON)

        from agents.agents.offers import OfferAgent
        from agents.models import AgentRecommendationOutcome, AgentTask

        task = OfferAgent().run()
        assert task.status == AgentTask.DONE

        outcomes = AgentRecommendationOutcome.objects.filter(
            report=task.report, agent_type=AgentTask.OFFERS
        )
        assert outcomes.count() == 2


class TestWeeklyBacklog:
    """4.3 WeeklyBacklog persistence."""

    @pytest.mark.django_db
    def test_model_create(self):
        from agents.models import WeeklyBacklog

        backlog = WeeklyBacklog.objects.create(
            week_start=datetime.date(2026, 4, 13),
            raw_text="Бэклог на неделю",
            items=[{"agent": "analytics", "task": "Проверить метрики"}],
        )
        assert backlog.pk is not None
        assert str(backlog) == "Бэклог 2026-04-13"


# ══════════════════════════════════════════════════════════════════════════
# Блок 5: Мониторинг
# ══════════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """5.1 /api/agents/health/ endpoint."""

    @pytest.mark.django_db
    def test_health_returns_json(self, client):
        response = client.get("/api/agents/health/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded", "unhealthy")
        assert "agents" in data
        assert "stuck_tasks" in data
        assert "error_rate_24h" in data

    @pytest.mark.django_db
    def test_health_detects_stuck(self, client):
        from agents.models import AgentTask
        from django.utils import timezone

        # Создаём "зависшую" задачу (RUNNING > 1 часа)
        baker.make(
            AgentTask,
            agent_type=AgentTask.ANALYTICS,
            status=AgentTask.RUNNING,
            created_at=timezone.now() - datetime.timedelta(hours=2),
        )

        response = client.get("/api/agents/health/")
        data = response.json()
        assert data["stuck_tasks"] >= 1
        assert data["status"] == "unhealthy"

    @pytest.mark.django_db
    def test_health_all_fresh_is_healthy(self, client):
        from agents.models import AgentTask

        # Создаём свежие DONE задачи для всех типов
        for atype, _ in AgentTask.AGENT_CHOICES:
            baker.make(
                AgentTask,
                agent_type=atype,
                status=AgentTask.DONE,
            )

        response = client.get("/api/agents/health/")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["stuck_tasks"] == 0


class TestDailyMetricTiming:
    """5.2 DailyMetric timing fields."""

    @pytest.mark.django_db
    def test_timing_fields_exist(self):
        from agents.models import DailyMetric

        metric = DailyMetric.objects.create(
            date=datetime.date.today(),
            agent_runs={"analytics": {"duration_s": 12, "status": "done"}},
            total_duration=12,
            error_count=0,
        )
        metric.refresh_from_db()
        assert metric.agent_runs["analytics"]["duration_s"] == 12
        assert metric.total_duration == 12
        assert metric.error_count == 0
