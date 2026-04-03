"""
Тесты для agents/integrations: YandexMetrikaClient, YandexDirectClient, VkAdsClient.
Все тесты используют моки — реальные API не вызываются.
"""
import pytest
from unittest.mock import MagicMock, patch


# ─── YandexMetrikaClient ────────────────────────────────────────────────────

class TestYandexMetrikaClient:

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_get_summary_parses_totals(self, mock_get):
        """3 метрики: visits, bounceRate, pageDepth. Все запросы возвращают один мок."""
        # get_summary делает 3 запроса: main totals, goals (optional), sources (optional)
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {"totals": [1500, 35.2, 3.1], "data": []},
        )
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="12345")
        result = client.get_summary("2026-01-01", "2026-01-31")
        assert result["sessions"] == 1500
        assert result["bounce_rate"] == 35.2
        assert result["page_depth"] == 3.1
        assert result["goal_reaches"] == 0   # нет целей в data=[]
        assert result["top_sources"] == []   # нет источников в data=[]

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_get_summary_parses_sources(self, mock_get):
        """3 запроса: totals → goals (нет данных) → источники трафика."""
        totals_resp = MagicMock(ok=True, json=lambda: {"totals": [100, 20.0, 2.0], "data": []})
        goals_resp  = MagicMock(ok=True, json=lambda: {"data": []})   # нет целей
        sources_resp = MagicMock(ok=True, json=lambda: {
            "data": [
                {"dimensions": [{"name": "organic"}], "metrics": [80]},
                {"dimensions": [{"name": "direct"}],  "metrics": [20]},
            ]
        })
        mock_get.side_effect = [totals_resp, goals_resp, sources_resp]
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


# ─── VkAdsClient ──────────────────────────────────────────────────────────────

class TestVkAdsClient:

    @patch("agents.integrations.vk_ads.requests.request")
    def test_get_campaign_stats_parses_response(self, mock_req):
        """Парсит items/rows, суммирует clicks/shows/spent по нескольким планам и дням."""
        plans_resp = MagicMock(ok=True, json=lambda: {
            "items": [{"id": 1, "name": "Кампания А"}, {"id": 2, "name": "Кампания Б"}],
            "count": 2,
        })
        stats_resp = MagicMock(ok=True, json=lambda: {
            "items": [
                {"id": 1, "rows": [
                    {"date": "2026-01-10", "base": {"clicks": 100, "shows": 4000, "spent": 8000.0}},
                    {"date": "2026-01-11", "base": {"clicks": 50,  "shows": 2000, "spent": 3500.0}},
                ]},
                {"id": 2, "rows": [
                    {"date": "2026-01-10", "base": {"clicks": 30,  "shows": 1000, "spent": 1200.0}},
                ]},
            ]
        })
        mock_req.side_effect = [plans_resp, stats_resp]
        from agents.integrations.vk_ads import VkAdsClient
        client = VkAdsClient(token="fake", account_id="999")
        result = client.get_campaign_stats("2026-01-10", "2026-01-11")
        assert result["clicks"] == 180
        assert result["impressions"] == 7000
        assert result["cost"] == 12700.0
        assert result["campaigns_count"] == 2

    @patch("agents.integrations.vk_ads.requests.request")
    def test_ctr_calculation(self, mock_req):
        """CTR = clicks / shows * 100, округление до 2 знаков."""
        plans_resp = MagicMock(ok=True, json=lambda: {
            "items": [{"id": 1}], "count": 1,
        })
        stats_resp = MagicMock(ok=True, json=lambda: {
            "items": [{"id": 1, "rows": [
                {"date": "2026-01-10", "base": {"clicks": 50, "shows": 1000, "spent": 5000.0}},
            ]}]
        })
        mock_req.side_effect = [plans_resp, stats_resp]
        from agents.integrations.vk_ads import VkAdsClient
        client = VkAdsClient(token="fake", account_id="99")
        result = client.get_campaign_stats("2026-01-10", "2026-01-10")
        assert result["ctr"] == 5.0

    @patch("agents.integrations.vk_ads.requests.request")
    def test_empty_plans_returns_zeros(self, mock_req):
        """Нет кампаний → все метрики 0, второй запрос (статистика) не делается."""
        mock_req.return_value = MagicMock(ok=True, json=lambda: {"items": [], "count": 0})
        from agents.integrations.vk_ads import VkAdsClient
        client = VkAdsClient(token="fake", account_id="99")
        result = client.get_campaign_stats("2026-01-01", "2026-01-31")
        assert result["impressions"] == 0
        assert result["clicks"] == 0
        assert result["cost"] == 0.0
        assert result["ctr"] == 0.0
        assert result["campaigns_count"] == 0
        assert mock_req.call_count == 1  # только listing, без stats

    @patch("agents.integrations.vk_ads.requests.request")
    def test_empty_rows_returns_zeros(self, mock_req):
        """Кампании есть, но за период данных нет → нули, campaigns_count == 0."""
        plans_resp = MagicMock(ok=True, json=lambda: {
            "items": [{"id": 1}], "count": 1,
        })
        stats_resp = MagicMock(ok=True, json=lambda: {
            "items": [{"id": 1, "rows": []}]
        })
        mock_req.side_effect = [plans_resp, stats_resp]
        from agents.integrations.vk_ads import VkAdsClient
        client = VkAdsClient(token="fake", account_id="99")
        result = client.get_campaign_stats("2026-01-01", "2026-01-31")
        assert result["clicks"] == 0
        assert result["campaigns_count"] == 0
        assert result["ctr"] == 0.0

    @patch("agents.integrations.vk_ads.requests.request")
    def test_request_raises_on_http_error(self, mock_req):
        """HTTP 403 → VkAdsError с 'HTTP 403' в сообщении."""
        mock_req.return_value = MagicMock(ok=False, status_code=403, text="Forbidden")
        from agents.integrations.vk_ads import VkAdsClient, VkAdsError
        client = VkAdsClient(token="bad", account_id="1")
        with pytest.raises(VkAdsError, match="HTTP 403"):
            client._request("GET", "ad_plans.json")

    @patch("agents.integrations.vk_ads.requests.request")
    def test_request_raises_on_network_error(self, mock_req):
        """ConnectionError → VkAdsError с 'Network error'."""
        import requests as req_lib
        mock_req.side_effect = req_lib.exceptions.ConnectionError("timeout")
        from agents.integrations.vk_ads import VkAdsClient, VkAdsError
        client = VkAdsClient(token="fake", account_id="1")
        with pytest.raises(VkAdsError, match="Network error"):
            client._request("GET", "ad_plans.json")

    def test_from_settings_raises_without_token(self, settings):
        """VK_ADS_TOKEN пустой → VkAdsError."""
        settings.VK_ADS_TOKEN = ""
        settings.VK_ADS_ACCOUNT_ID = "12345"
        from agents.integrations.vk_ads import VkAdsClient, VkAdsError
        with pytest.raises(VkAdsError):
            VkAdsClient.from_settings()

    def test_from_settings_raises_without_account_id(self, settings):
        """VK_ADS_ACCOUNT_ID пустой → VkAdsError."""
        settings.VK_ADS_TOKEN = "sometoken"
        settings.VK_ADS_ACCOUNT_ID = ""
        from agents.integrations.vk_ads import VkAdsClient, VkAdsError
        with pytest.raises(VkAdsError):
            VkAdsClient.from_settings()

    def test_from_settings_ok(self, settings):
        """Корректные настройки → клиент создаётся с нужными полями."""
        settings.VK_ADS_TOKEN = "mytoken"
        settings.VK_ADS_ACCOUNT_ID = "777"
        from agents.integrations.vk_ads import VkAdsClient
        client = VkAdsClient.from_settings()
        assert client.token == "mytoken"
        assert client.account_id == "777"


# ─── YandexWebmasterClient — новые методы ───────────────────────────────────


class TestYandexWebmasterClientNewMethods:
    """
    Тесты для get_query_stats() и get_page_stats().
    Оба метода — graceful wrappers над get_top_queries/get_top_pages:
    при YandexWebmasterError возвращают [] вместо исключения.
    """

    @patch("agents.integrations.yandex_webmaster.requests.request")
    def test_get_query_stats_returns_list(self, mock_req):
        """Успешный ответ — возвращает список запросов с нужными полями."""
        # user_id="42" передан в конструктор → get_user_id() не вызывает API
        mock_req.return_value = MagicMock(ok=True, json=lambda: {
            "queries": [
                {
                    "query_text": "массаж пенза",
                    "indicators": [
                        {"query_indicator": "TOTAL_CLICKS",      "value": 150},
                        {"query_indicator": "TOTAL_SHOWS",       "value": 3000},
                        {"query_indicator": "AVG_SHOW_POSITION", "value": 4.2},
                    ],
                }
            ]
        })
        from agents.integrations.yandex_webmaster import YandexWebmasterClient
        client = YandexWebmasterClient(
            token="fake", user_id="42", host_id="https:example.ru:443"
        )
        result = client.get_query_stats("2026-02-01", "2026-02-07")
        assert len(result) == 1
        assert result[0]["query"] == "массаж пенза"
        assert result[0]["clicks"] == 150
        assert result[0]["impressions"] == 3000
        assert result[0]["ctr"] == round(150 / 3000, 4)
        assert result[0]["avg_position"] == 4.2

    @patch("agents.integrations.yandex_webmaster.requests.request")
    def test_get_query_stats_returns_empty_on_api_error(self, mock_req):
        """При ошибке API — возвращает [], не бросает исключение."""
        mock_req.return_value = MagicMock(
            ok=False, status_code=500, text="Internal Server Error"
        )
        from agents.integrations.yandex_webmaster import YandexWebmasterClient
        client = YandexWebmasterClient(
            token="fake", user_id="42", host_id="https:example.ru:443"
        )
        result = client.get_query_stats("2026-02-01", "2026-02-07")
        assert result == []

    @patch("agents.integrations.yandex_webmaster.requests.request")
    def test_get_page_stats_returns_list(self, mock_req):
        """Успешный ответ — возвращает список страниц с url и метриками."""
        mock_req.return_value = MagicMock(ok=True, json=lambda: {
            "queries": [
                {
                    "url": "/massazh-spiny/",
                    "query_text": "/massazh-spiny/",
                    "indicators": [
                        {"query_indicator": "TOTAL_CLICKS",      "value": 80},
                        {"query_indicator": "TOTAL_SHOWS",       "value": 1200},
                        {"query_indicator": "AVG_SHOW_POSITION", "value": 6.1},
                    ],
                }
            ]
        })
        from agents.integrations.yandex_webmaster import YandexWebmasterClient
        client = YandexWebmasterClient(
            token="fake", user_id="42", host_id="https:example.ru:443"
        )
        result = client.get_page_stats("2026-02-01", "2026-02-07")
        assert len(result) == 1
        assert result[0]["clicks"] == 80
        assert result[0]["impressions"] == 1200

    @patch("agents.integrations.yandex_webmaster.requests.request")
    def test_get_page_stats_returns_empty_on_api_error(self, mock_req):
        """При ошибке API — возвращает [], не бросает исключение."""
        mock_req.return_value = MagicMock(
            ok=False, status_code=403, text="Forbidden"
        )
        from agents.integrations.yandex_webmaster import YandexWebmasterClient
        client = YandexWebmasterClient(
            token="fake", user_id="42", host_id="https:example.ru:443"
        )
        result = client.get_page_stats("2026-02-01", "2026-02-07")
        assert result == []

    @patch("agents.integrations.yandex_webmaster.requests.request")
    def test_get_query_stats_empty_queries(self, mock_req):
        """API вернул пустой список queries — возвращаем []."""
        mock_req.return_value = MagicMock(
            ok=True, json=lambda: {"queries": []}
        )
        from agents.integrations.yandex_webmaster import YandexWebmasterClient
        client = YandexWebmasterClient(
            token="fake", user_id="42", host_id="https:example.ru:443"
        )
        result = client.get_query_stats("2026-02-01", "2026-02-07")
        assert result == []


# ─── Yandex Metrika: get_organic_sessions / get_page_behavior ────────────


class TestYandexMetrikaClientNewMethods:
    """Тесты для get_organic_sessions() и get_page_behavior()."""

    # ── get_organic_sessions ──────────────────────────────────────────

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_organic_sessions_success(self, mock_get):
        """Organic row найден — возвращаем sessions, bounce_rate, avg_depth."""
        mock_get.side_effect = [
            # 1-й вызов: источники трафика
            MagicMock(ok=True, json=lambda: {
                "data": [
                    {
                        "dimensions": [{"name": "Переходы из поисковых систем"}],
                        "metrics": [120, 35.5, 2.4],
                    },
                    {
                        "dimensions": [{"name": "Прямые заходы"}],
                        "metrics": [80, 50.0, 1.1],
                    },
                ],
            }),
            # 2-й вызов: цели из органики
            MagicMock(ok=True, json=lambda: {
                "data": [
                    {
                        "dimensions": [{"name": "Переходы из поисковых систем"}, {"name": "Заявка"}],
                        "metrics": [5],
                    },
                    {
                        "dimensions": [{"name": "Переходы из поисковых систем"}, {"name": "Звонок"}],
                        "metrics": [3],
                    },
                ],
            }),
        ]
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        result = client.get_organic_sessions("2026-02-01", "2026-02-07")
        assert result["sessions"] == 120
        assert result["bounce_rate"] == 35.5
        assert result["avg_depth"] == 2.4
        assert result["goal_conversions"] == 8  # 5 + 3

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_organic_sessions_no_organic_row(self, mock_get):
        """Нет organic-строки — sessions=0."""
        mock_get.side_effect = [
            MagicMock(ok=True, json=lambda: {
                "data": [
                    {
                        "dimensions": [{"name": "Прямые заходы"}],
                        "metrics": [80, 50.0, 1.1],
                    },
                ],
            }),
            MagicMock(ok=True, json=lambda: {"data": []}),
        ]
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        result = client.get_organic_sessions("2026-02-01", "2026-02-07")
        assert result["sessions"] == 0
        assert result["goal_conversions"] == 0

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_organic_sessions_api_error(self, mock_get):
        """Ошибка API — возвращаем нулевой dict."""
        mock_get.return_value = MagicMock(
            ok=False, status_code=500, text="Internal Server Error"
        )
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        result = client.get_organic_sessions("2026-02-01", "2026-02-07")
        assert result == {
            "sessions": 0,
            "bounce_rate": 0.0,
            "avg_depth": 0.0,
            "goal_conversions": 0,
        }

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_organic_sessions_goal_error_graceful(self, mock_get):
        """Первый запрос ОК, второй (цели) падает — goal_conversions=0, остальное ОК."""
        mock_get.side_effect = [
            MagicMock(ok=True, json=lambda: {
                "data": [
                    {
                        "dimensions": [{"name": "Organic search"}],
                        "metrics": [50, 40.0, 1.8],
                    },
                ],
            }),
            MagicMock(ok=False, status_code=403, text="Forbidden"),
        ]
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        result = client.get_organic_sessions("2026-02-01", "2026-02-07")
        assert result["sessions"] == 50
        assert result["goal_conversions"] == 0

    # ── get_page_behavior ─────────────────────────────────────────────

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_page_behavior_success(self, mock_get):
        """Успешный ответ — sessions, bounce_rate, time_on_page, goals."""
        mock_get.side_effect = [
            # 1-й вызов: метрики страницы
            MagicMock(ok=True, json=lambda: {
                "totals": [45, 28.3, 95.7],
            }),
            # 2-й вызов: цели страницы
            MagicMock(ok=True, json=lambda: {
                "data": [
                    {"metrics": [3]},
                    {"metrics": [2]},
                ],
            }),
        ]
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        result = client.get_page_behavior("/uslugi/massazh/", "2026-02-01", "2026-02-07")
        assert result["sessions"] == 45
        assert result["bounce_rate"] == 28.3
        assert result["time_on_page"] == 95.7
        assert result["goal_conversions"] == 5  # 3 + 2

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_page_behavior_empty_totals(self, mock_get):
        """Пустые totals — возвращаем нули."""
        mock_get.side_effect = [
            MagicMock(ok=True, json=lambda: {"totals": []}),
            MagicMock(ok=True, json=lambda: {"data": []}),
        ]
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        result = client.get_page_behavior("/uslugi/massazh/", "2026-02-01", "2026-02-07")
        assert result["sessions"] == 0
        assert result["bounce_rate"] == 0.0
        assert result["time_on_page"] == 0.0
        assert result["goal_conversions"] == 0

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_page_behavior_api_error(self, mock_get):
        """Ошибка API — нулевой dict."""
        mock_get.return_value = MagicMock(
            ok=False, status_code=500, text="Error"
        )
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        result = client.get_page_behavior("/uslugi/massazh/", "2026-02-01", "2026-02-07")
        assert result == {
            "sessions": 0,
            "bounce_rate": 0.0,
            "time_on_page": 0.0,
            "goal_conversions": 0,
        }

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_page_behavior_goal_error_graceful(self, mock_get):
        """Первый запрос ОК, второй (цели) падает — goals=0, остальное ОК."""
        mock_get.side_effect = [
            MagicMock(ok=True, json=lambda: {"totals": [10, 55.0, 30.2]}),
            MagicMock(ok=False, status_code=403, text="Forbidden"),
        ]
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        result = client.get_page_behavior("/uslugi/massazh/", "2026-02-01", "2026-02-07")
        assert result["sessions"] == 10
        assert result["goal_conversions"] == 0

    @patch("agents.integrations.yandex_metrika.requests.get")
    def test_page_behavior_filter_contains_url(self, mock_get):
        """Проверяем что URL передаётся в filters параметр."""
        mock_get.side_effect = [
            MagicMock(ok=True, json=lambda: {"totals": [1, 0.0, 0.0]}),
            MagicMock(ok=True, json=lambda: {"data": []}),
        ]
        from agents.integrations.yandex_metrika import YandexMetrikaClient
        client = YandexMetrikaClient(token="fake", counter_id="123")
        client.get_page_behavior("/uslugi/massazh/", "2026-02-01", "2026-02-07")
        first_call_params = mock_get.call_args_list[0]
        params = first_call_params.kwargs.get("params", {})
        assert "/uslugi/massazh/" in params.get("filters", "")
