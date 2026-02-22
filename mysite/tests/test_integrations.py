"""
Тесты для agents/integrations: YandexMetrikaClient, YandexDirectClient.
Все тесты используют моки — реальные API не вызываются.
"""
import pytest
from unittest.mock import MagicMock, patch


# ─── YandexMetrikaClient ────────────────────────────────────────────────────

class TestYandexMetrikaClient:

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_get_summary_parses_totals(self, mock_get):
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"totals": [1500, 35.2, 42, 3.1], "data": []},
        )
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="12345")
        result = client.get_summary("2026-01-01", "2026-01-31")
        assert result["sessions"] == 1500
        assert result["bounce_rate"] == 35.2
        assert result["goal_reaches"] == 42
        assert result["page_depth"] == 3.1

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_get_summary_parses_sources(self, mock_get):
        """Два запроса: totals + источники трафика."""
        totals_resp = MagicMock(ok=True, json=lambda: {"totals": [100, 20.0, 5, 2.0], "data": []})
        sources_resp = MagicMock(ok=True, json=lambda: {
            "data": [
                {"dimensions": [{"name": "organic"}], "metrics": [80]},
                {"dimensions": [{"name": "direct"}],  "metrics": [20]},
            ]
        })
        mock_get.side_effect = [totals_resp, sources_resp]
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="99")
        result = client.get_summary("2026-01-01", "2026-01-31")
        assert len(result["top_sources"]) == 2
        assert result["top_sources"][0]["source"] == "organic"
        assert result["top_sources"][0]["visits"] == 80

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_get_summary_empty_totals(self, mock_get):
        """Если Метрика вернула пустые totals — возвращаем нули."""
        mock_get.return_value = MagicMock(ok=True, json=lambda: {"totals": [], "data": []})
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="1")
        result = client.get_summary("2026-01-01", "2026-01-31")
        assert result["sessions"] == 0
        assert result["bounce_rate"] == 0.0

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_request_raises_on_http_error(self, mock_get):
        mock_get.return_value = MagicMock(ok=False, status_code=403, text="Forbidden")
        from agents.integrations.yandex_metrika import YandexMetrikaClient, YandexMetrikaError
        client = YandexMetrikaClient(token="bad", counter_id="1")
        with pytest.raises(YandexMetrikaError, match="HTTP 403"):
            client._request({"id": "1", "metrics": "ym:s:visits", "date1": "2026-01-01", "date2": "2026-01-31"})

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_request_raises_on_network_error(self, mock_get):
        import requests as req
        mock_get.side_effect = req.exceptions.ConnectionError("timeout")
        from agents.integrations.yandex_metrika import YandexMetrikaClient, YandexMetrikaError
        client = YandexMetrikaClient(token="fake", counter_id="1")
        with pytest.raises(YandexMetrikaError, match="Network error"):
            client._request({"id": "1", "metrics": "ym:s:visits", "date1": "2026-01-01", "date2": "2026-01-31"})

    def test_from_settings_raises_without_token(self, settings):
        settings.YANDEX_METRIKA_TOKEN = ""
        settings.YANDEX_METRIKA_COUNTER_ID = ""
        from agents.integrations.yandex_metrika import YandexMetrikaClient, YandexMetrikaError
        with pytest.raises(YandexMetrikaError):
            YandexMetrikaClient.from_settings()

    def test_from_settings_raises_without_counter_id(self, settings):
        settings.YANDEX_METRIKA_TOKEN = "some-token"
        settings.YANDEX_METRIKA_COUNTER_ID = ""
        from agents.integrations.yandex_metrika import YandexMetrikaClient, YandexMetrikaError
        with pytest.raises(YandexMetrikaError):
            YandexMetrikaClient.from_settings()

    def test_from_settings_ok(self, settings):
        settings.YANDEX_METRIKA_TOKEN = "tok"
        settings.YANDEX_METRIKA_COUNTER_ID = "123"
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient.from_settings()
        assert client.token == "tok"
        assert client.counter_id == "123"


# ─── YandexDirectClient ─────────────────────────────────────────────────────

class TestYandexDirectClient:

    @patch("agents.integrations.yandex_direct.requests.post")
    def test_get_campaign_stats_parses_tsv(self, mock_post):
        tsv = (
            "CampaignName\tClicks\tImpressions\tCost\tCtr\n"
            "Кампания 1\t150\t5000\t12000.50\t3.0\n"
            "Кампания 2\t80\t3000\t6000.00\t2.67\n"
        )
        mock_post.return_value = MagicMock(status_code=200, text=tsv)
        from agents.integrations.yandex_direct import YandexDirectClient
        client = YandexDirectClient(token="fake", client_login="login")
        result = client.get_campaign_stats("2026-01-01", "2026-01-31")
        assert result["clicks"] == 230
        assert result["impressions"] == 8000
        assert result["cost"] == 18000.5
        assert result["campaigns_count"] == 2

    @patch("agents.integrations.yandex_direct.requests.post")
    def test_get_campaign_stats_empty_tsv(self, mock_post):
        """Пустой отчёт — нули, 0 кампаний."""
        tsv = "CampaignName\tClicks\tImpressions\tCost\tCtr\n"
        mock_post.return_value = MagicMock(status_code=200, text=tsv)
        from agents.integrations.yandex_direct import YandexDirectClient
        client = YandexDirectClient(token="fake", client_login="login")
        result = client.get_campaign_stats("2026-01-01", "2026-01-31")
        assert result["clicks"] == 0
        assert result["campaigns_count"] == 0
        assert result["ctr"] == 0.0

    @patch("agents.integrations.yandex_direct.time.sleep")
    @patch("agents.integrations.yandex_direct.requests.post")
    def test_request_retries_on_202(self, mock_post, mock_sleep):
        """202 → спит → повторяет → 200."""
        tsv = "CampaignName\tClicks\tImpressions\tCost\tCtr\nКампания\t10\t100\t500\t10.0\n"
        mock_post.side_effect = [
            MagicMock(status_code=202, headers={"retryIn": "2"}),
            MagicMock(status_code=200, text=tsv),
        ]
        from agents.integrations.yandex_direct import YandexDirectClient
        client = YandexDirectClient(token="fake", client_login="login")
        result = client.get_campaign_stats("2026-01-01", "2026-01-31")
        assert result["clicks"] == 10
        mock_sleep.assert_called_once()

    @patch("agents.integrations.yandex_direct.requests.post")
    def test_request_raises_on_http_error(self, mock_post):
        mock_post.return_value = MagicMock(status_code=401, text="Unauthorized")
        from agents.integrations.yandex_direct import YandexDirectClient, YandexDirectError
        client = YandexDirectClient(token="bad", client_login="login")
        with pytest.raises(YandexDirectError, match="HTTP 401"):
            client._request({"params": {}})

    @patch("agents.integrations.yandex_direct.time.sleep")
    @patch("agents.integrations.yandex_direct.requests.post")
    def test_request_raises_after_max_retries(self, mock_post, mock_sleep):
        """Если всегда 202 — поднимает YandexDirectError."""
        mock_post.return_value = MagicMock(status_code=202, headers={"retryIn": "1"})
        from agents.integrations.yandex_direct import YandexDirectClient, YandexDirectError
        client = YandexDirectClient(token="fake", client_login="login")
        with pytest.raises(YandexDirectError, match="не готов"):
            client._request({"params": {}}, max_retries=2)

    def test_from_settings_raises_without_token(self, settings):
        settings.YANDEX_DIRECT_TOKEN = ""
        settings.YANDEX_DIRECT_CLIENT_LOGIN = ""
        from agents.integrations.yandex_direct import YandexDirectClient, YandexDirectError
        with pytest.raises(YandexDirectError):
            YandexDirectClient.from_settings()

    def test_from_settings_ok(self, settings):
        settings.YANDEX_DIRECT_TOKEN = "tok"
        settings.YANDEX_DIRECT_CLIENT_LOGIN = "mylogin"
        from agents.integrations.yandex_direct import YandexDirectClient
        client = YandexDirectClient.from_settings()
        assert client.token == "tok"
        assert client.client_login == "mylogin"

    @patch("agents.integrations.yandex_direct.requests.post")
    def test_ctr_calculation(self, mock_post):
        """CTR вычисляется правильно: clicks/impressions*100."""
        tsv = "CampaignName\tClicks\tImpressions\tCost\tCtr\nК\t50\t1000\t5000\t5.0\n"
        mock_post.return_value = MagicMock(status_code=200, text=tsv)
        from agents.integrations.yandex_direct import YandexDirectClient
        client = YandexDirectClient(token="t", client_login="l")
        result = client.get_campaign_stats("2026-01-01", "2026-01-31")
        assert result["ctr"] == 5.0
