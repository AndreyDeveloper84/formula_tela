"""
Тесты для TrendScoutAgent, YandexSuggestClient, VkSocialClient.
"""
import json
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from model_bakery import baker


# ── Интеграции ─────────────────────────────────────────────────────────


class TestYandexSuggestClient:
    def test_parse_suggestions(self):
        from agents.integrations.trend_parser import YandexSuggestClient

        client = YandexSuggestClient(proxy_url="")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            "массаж пенза",
            ["массаж пенза цены", "массаж пенза отзывы", "массаж пенза акции"],
        ]

        with patch("agents.integrations.trend_parser.requests.get", return_value=mock_response):
            result = client.get_suggestions("массаж пенза")

        assert result == ["массаж пенза цены", "массаж пенза отзывы", "массаж пенза акции"]

    def test_parse_empty_response(self):
        from agents.integrations.trend_parser import YandexSuggestClient

        client = YandexSuggestClient(proxy_url="")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = []

        with patch("agents.integrations.trend_parser.requests.get", return_value=mock_response):
            result = client.get_suggestions("тест")

        assert result == []

    def test_proxy_passed(self):
        from agents.integrations.trend_parser import YandexSuggestClient

        client = YandexSuggestClient(proxy_url="http://proxy:8080")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = ["q", []]

        with patch("agents.integrations.trend_parser.requests.get", return_value=mock_response) as mock_get:
            client.get_suggestions("тест")

        _, kwargs = mock_get.call_args
        assert kwargs["proxies"] == {"https": "http://proxy:8080", "http": "http://proxy:8080"}

    def test_collect_trends(self):
        from agents.integrations.trend_parser import YandexSuggestClient

        client = YandexSuggestClient(proxy_url="")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = ["q", ["suggestion1", "suggestion2"]]

        with patch("agents.integrations.trend_parser.requests.get", return_value=mock_response):
            with patch("agents.integrations.trend_parser.time.sleep"):
                result = client.collect_trends(["массаж", "спа"])

        assert len(result) == 2
        assert result[0]["seed"] == "массаж"
        assert result[0]["suggestions"] == ["suggestion1", "suggestion2"]

    def test_network_error_graceful(self):
        import requests as req
        from agents.integrations.trend_parser import YandexSuggestClient

        client = YandexSuggestClient(proxy_url="")

        with patch("agents.integrations.trend_parser.requests.get", side_effect=req.ConnectionError("fail")):
            result = client.get_suggestions("тест")

        assert result == []


class TestVkSocialClient:
    def test_parse_wall_posts(self):
        from agents.integrations.trend_parser import VkSocialClient

        client = VkSocialClient(service_token="test", proxy_url="")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "response": {
                "count": 1,
                "items": [
                    {
                        "text": "Массаж спины — лучшее средство от стресса! Записывайтесь на приём.",
                        "likes": {"count": 50},
                        "comments": {"count": 10},
                        "reposts": {"count": 5},
                        "views": {"count": 500},
                        "date": 1744300000,  # ~2025-04-10
                    },
                ],
            }
        }

        with patch("agents.integrations.trend_parser.requests.get", return_value=mock_response):
            posts = client.get_wall_posts("12345")

        assert len(posts) == 1
        assert posts[0]["likes"] == 50
        assert posts[0]["comments"] == 10
        assert "Массаж спины" in posts[0]["text"]

    def test_skip_short_posts(self):
        from agents.integrations.trend_parser import VkSocialClient

        client = VkSocialClient(service_token="test", proxy_url="")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "response": {
                "count": 1,
                "items": [
                    {"text": "Короткий", "likes": {"count": 1}, "comments": {"count": 0},
                     "reposts": {"count": 0}, "views": {"count": 10}, "date": 1744300000},
                ],
            }
        }

        with patch("agents.integrations.trend_parser.requests.get", return_value=mock_response):
            posts = client.get_wall_posts("12345")

        assert len(posts) == 0  # <20 chars filtered out

    def test_no_token_raises(self, settings):
        from agents.integrations.trend_parser import VkSocialClient, VkSocialError

        settings.VK_SERVICE_TOKEN = ""
        with pytest.raises(VkSocialError, match="VK_SERVICE_TOKEN"):
            VkSocialClient.from_settings()

    def test_api_error_graceful(self):
        from agents.integrations.trend_parser import VkSocialClient

        client = VkSocialClient(service_token="test", proxy_url="")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "error": {"error_code": 15, "error_msg": "Access denied"}
        }

        with patch("agents.integrations.trend_parser.requests.get", return_value=mock_response):
            posts = client.get_wall_posts("12345")

        assert posts == []

    def test_engagement_sort(self):
        from agents.integrations.trend_parser import VkSocialClient

        client = VkSocialClient(service_token="test", proxy_url="")

        posts_data = {
            "response": {
                "count": 2,
                "items": [
                    {"text": "Пост с малым engagement текстом побольше",
                     "likes": {"count": 5}, "comments": {"count": 0},
                     "reposts": {"count": 0}, "views": {"count": 100},
                     "date": 1775800000},
                    {"text": "Пост с большим engagement текстом побольше",
                     "likes": {"count": 50}, "comments": {"count": 20},
                     "reposts": {"count": 10}, "views": {"count": 1000},
                     "date": 1775800000},
                ],
            }
        }
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = posts_data

        with patch("agents.integrations.trend_parser.requests.get", return_value=mock_response):
            with patch("agents.integrations.trend_parser.time.sleep"):
                top = client.collect_top_posts(["12345"], days=365, top_n=2)

        assert len(top) == 2
        assert top[0]["engagement"] > top[1]["engagement"]


# ── Модель TrendSnapshot ──────────────────────────────────────────────


@pytest.mark.django_db
class TestTrendSnapshotModel:
    def test_create(self):
        from agents.models import TrendSnapshot

        snap = TrendSnapshot.objects.create(
            source=TrendSnapshot.SOURCE_YANDEX,
            date=date.today(),
            raw_data=[{"seed": "test", "suggestions": ["a", "b"]}],
            summary="Тест",
            trends=[{"topic": "массаж", "score": 8, "source": "yandex", "detail": "растёт"}],
        )
        assert snap.pk
        assert "Яндекс" in str(snap)

    def test_unique_together(self):
        from django.db import IntegrityError
        from agents.models import TrendSnapshot

        TrendSnapshot.objects.create(
            source=TrendSnapshot.SOURCE_YANDEX,
            date=date.today(),
            raw_data=[],
        )
        with pytest.raises(IntegrityError):
            TrendSnapshot.objects.create(
                source=TrendSnapshot.SOURCE_YANDEX,
                date=date.today(),
                raw_data=[],
            )


# ── TrendScoutAgent ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestTrendScoutAgent:
    @pytest.fixture
    def mock_parsers(self):
        """Мокаем оба парсера."""
        yandex_data = [
            {"seed": "массаж пенза", "suggestions": ["массаж пенза цены", "массаж пенза акции"]},
            {"seed": "спа пенза", "suggestions": ["спа пенза недорого"]},
        ]
        vk_data = [
            {"text": "Антицеллюлитный массаж — хит сезона", "likes": 100,
             "comments": 20, "reposts": 10, "views": 2000,
             "date": "2026-04-01", "group_id": "12345", "engagement": 180},
        ]

        with patch("agents.agents.trend_scout.TrendScoutAgent.gather_yandex_data", return_value=yandex_data), \
             patch("agents.agents.trend_scout.TrendScoutAgent.gather_vk_data", return_value=vk_data):
            yield yandex_data, vk_data

    @pytest.fixture
    def mock_openai(self):
        """Мокаем OpenAI."""
        gpt_response = json.dumps({
            "summary": "Антицеллюлитный массаж в тренде. Спрос на SPA растёт.",
            "trends": [
                {"topic": "Антицеллюлитный массаж", "score": 9, "source": "both", "detail": "Растущий спрос"},
                {"topic": "SPA для двоих", "score": 7, "source": "vk", "detail": "Популярно в VK"},
            ],
        })
        mock_choice = MagicMock()
        mock_choice.message.content = gpt_response
        mock_resp = MagicMock()
        mock_resp.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_resp

        with patch("agents.agents.trend_scout.get_openai_client", return_value=mock_client):
            yield mock_client

    @pytest.fixture
    def mock_telegram(self):
        with patch("agents.agents.trend_scout.send_telegram") as mock:
            yield mock

    def test_run_success(self, mock_parsers, mock_openai, mock_telegram):
        from agents.agents.trend_scout import TrendScoutAgent
        from agents.models import AgentTask

        task = TrendScoutAgent().run()

        assert task.status == AgentTask.DONE
        assert task.agent_type == AgentTask.TREND_SCOUT
        assert task.report.summary == "Антицеллюлитный массаж в тренде. Спрос на SPA растёт."
        assert len(task.report.recommendations) == 2

    def test_creates_snapshots(self, mock_parsers, mock_openai, mock_telegram):
        from agents.agents.trend_scout import TrendScoutAgent
        from agents.models import TrendSnapshot

        TrendScoutAgent().run()

        assert TrendSnapshot.objects.filter(source=TrendSnapshot.SOURCE_YANDEX).exists()
        assert TrendSnapshot.objects.filter(source=TrendSnapshot.SOURCE_VK).exists()

        snap = TrendSnapshot.objects.get(source=TrendSnapshot.SOURCE_YANDEX)
        assert len(snap.trends) == 2

    def test_telegram_called(self, mock_parsers, mock_openai, mock_telegram):
        from agents.agents.trend_scout import TrendScoutAgent

        TrendScoutAgent().run()

        assert mock_telegram.called
        call_text = mock_telegram.call_args[0][0]
        assert "Разведка трендов" in call_text
        assert "Антицеллюлитный массаж" in call_text

    def test_run_without_vk(self, mock_openai, mock_telegram):
        from agents.agents.trend_scout import TrendScoutAgent
        from agents.models import AgentTask

        yandex_data = [{"seed": "тест", "suggestions": ["тест1"]}]

        with patch("agents.agents.trend_scout.TrendScoutAgent.gather_yandex_data", return_value=yandex_data), \
             patch("agents.agents.trend_scout.TrendScoutAgent.gather_vk_data", return_value=[]):
            task = TrendScoutAgent().run()

        assert task.status == AgentTask.DONE


# ── OfferAgent с трендами ─────────────────────────────────────────────


@pytest.mark.django_db
class TestOfferAgentWithTrends:
    def test_prompt_includes_trends(self):
        from agents.models import TrendSnapshot
        from agents.agents.offers import _build_prompt

        TrendSnapshot.objects.create(
            source=TrendSnapshot.SOURCE_YANDEX,
            date=date.today(),
            raw_data=[],
            trends=[
                {"topic": "LPG массаж", "score": 9, "source": "yandex", "detail": "Растёт спрос"},
            ],
        )

        from agents.agents.offers import OfferAgent
        data = OfferAgent().gather_data()
        prompt = _build_prompt(data)

        assert "LPG массаж" in prompt
        assert "тренды рынка" in prompt.lower()

    def test_prompt_without_trends(self):
        from agents.agents.offers import OfferAgent, _build_prompt

        data = OfferAgent().gather_data()
        prompt = _build_prompt(data)

        # Промпт должен работать и без трендов
        assert "Данные салона" in prompt
        assert "Предложи" in prompt
