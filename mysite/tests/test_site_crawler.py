"""
Тесты для TechnicalSEOWatchdog.
Все HTTP-запросы замоканы — реальная сеть не используется.
БД используется через pytest-django (db фикстура).
"""
import pytest
from unittest.mock import MagicMock, patch
from model_bakery import baker


# ─── TechnicalSEOWatchdog ─────────────────────────────────────────────────────

class TestTechnicalSEOWatchdogInit:

    def test_from_settings_ok(self, settings):
        """from_settings() создаёт экземпляр из SITE_BASE_URL."""
        settings.SITE_BASE_URL = "https://formulatela.ru"
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog.from_settings()
        assert watchdog.base_url == "https://formulatela.ru"
        assert watchdog.timeout == 10

    def test_from_settings_strips_trailing_slash(self, settings):
        """Trailing slash в SITE_BASE_URL удаляется автоматически."""
        settings.SITE_BASE_URL = "https://formulatela.ru/"
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog.from_settings()
        assert watchdog.base_url == "https://formulatela.ru"

    def test_from_settings_raises_without_base_url(self, settings):
        """Без SITE_BASE_URL — TechnicalSEOError."""
        settings.SITE_BASE_URL = ""
        from agents.integrations.site_crawler import (
            TechnicalSEOWatchdog, TechnicalSEOError,
        )
        with pytest.raises(TechnicalSEOError):
            TechnicalSEOWatchdog.from_settings()

    def test_custom_timeout(self):
        """Timeout передаётся через конструктор."""
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://example.ru", timeout=5)
        assert watchdog.timeout == 5


class TestGetAllServiceUrls:

    @pytest.mark.django_db
    def test_returns_urls_for_active_services(self):
        """Активные услуги со slug → корректные URL."""
        baker.make("services_app.Service", slug="massazh-spiny", is_active=True)
        baker.make("services_app.Service", slug="lazernaya-epilyatsiya", is_active=True)
        baker.make("services_app.Service", is_active=False, slug="inactive")

        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        urls = watchdog.get_all_service_urls()

        # Только активные
        assert len(urls) == 2
        assert "https://formulatela.ru/uslugi/massazh-spiny/" in urls
        assert "https://formulatela.ru/uslugi/lazernaya-epilyatsiya/" in urls
        # Неактивная не попала
        assert "https://formulatela.ru/uslugi/inactive/" not in urls

    @pytest.mark.django_db
    def test_skips_services_without_slug(self):
        """Услуги без slug пропускаются, не вызывают ошибку."""
        baker.make("services_app.Service", slug="", is_active=True)
        baker.make("services_app.Service", slug="normalnyj", is_active=True)

        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        urls = watchdog.get_all_service_urls()

        assert len(urls) == 1
        assert "https://formulatela.ru/uslugi/normalnyj/" in urls

    @pytest.mark.django_db
    def test_empty_when_no_active_services(self):
        """Нет активных услуг → пустой список, не ошибка."""
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        urls = watchdog.get_all_service_urls()
        assert urls == []


class TestCheckUrl:

    @patch("agents.integrations.site_crawler.requests.get")
    def test_ok_returns_empty_issue(self, mock_get):
        """200 → issue == ''."""
        mock_get.return_value = MagicMock(status_code=200)
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog._check_url("https://formulatela.ru/uslugi/massazh/")
        assert result["status_code"] == 200
        assert result["issue"] == ""

    @patch("agents.integrations.site_crawler.requests.get")
    def test_404_returns_issue(self, mock_get):
        """404 → issue == 'HTTP 404'."""
        mock_get.return_value = MagicMock(status_code=404)
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog._check_url("https://formulatela.ru/uslugi/nesuschestvuet/")
        assert result["status_code"] == 404
        assert result["issue"] == "HTTP 404"

    @patch("agents.integrations.site_crawler.requests.get")
    def test_500_returns_issue(self, mock_get):
        """500 → issue == 'HTTP 500'."""
        mock_get.return_value = MagicMock(status_code=500)
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog._check_url("https://formulatela.ru/uslugi/broken/")
        assert result["status_code"] == 500
        assert result["issue"] == "HTTP 500"

    @patch("agents.integrations.site_crawler.requests.get")
    def test_timeout_returns_issue(self, mock_get):
        """Timeout → status_code=0, issue содержит 'timeout'."""
        import requests as req_lib
        mock_get.side_effect = req_lib.Timeout("timed out")
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog._check_url("https://formulatela.ru/uslugi/slow/")
        assert result["status_code"] == 0
        assert "timeout" in result["issue"]

    @patch("agents.integrations.site_crawler.requests.get")
    def test_connection_error_returns_issue(self, mock_get):
        """ConnectionError → status_code=0, issue содержит 'connection_error'."""
        import requests as req_lib
        mock_get.side_effect = req_lib.ConnectionError("refused")
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog._check_url("https://formulatela.ru/uslugi/down/")
        assert result["status_code"] == 0
        assert "connection_error" in result["issue"]

    @patch("agents.integrations.site_crawler.requests.get")
    def test_301_redirect_no_issue(self, mock_get):
        """301 редирект (allow_redirects=True) → финальный статус 200, нет issue."""
        mock_get.return_value = MagicMock(status_code=200)
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog._check_url("https://formulatela.ru/uslugi/massazh/")
        assert result["issue"] == ""


class TestCheckServicePages:

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_creates_seotask_on_404(self, mock_get):
        """404 → SeoTask с task_type='fix_technical' создаётся в БД."""
        mock_get.return_value = MagicMock(status_code=404)
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        from agents.models import SeoTask

        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        results = watchdog.check_service_pages(
            ["https://formulatela.ru/uslugi/nesuschestvuet/"]
        )

        assert len(results) == 1
        assert results[0]["status_code"] == 404
        assert results[0]["issue"] == "HTTP 404"

        task = SeoTask.objects.get(
            task_type=SeoTask.TYPE_FIX_TECHNICAL,
            target_url="/uslugi/nesuschestvuet/",
        )
        assert task.priority == SeoTask.PRIORITY_HIGH
        assert task.status == SeoTask.STATUS_OPEN
        assert task.payload["status_code"] == 404

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_no_seotask_on_200(self, mock_get):
        """200 → SeoTask НЕ создаётся."""
        mock_get.return_value = MagicMock(status_code=200)
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        from agents.models import SeoTask

        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        watchdog.check_service_pages(["https://formulatela.ru/uslugi/massazh/"])

        assert SeoTask.objects.filter(
            task_type=SeoTask.TYPE_FIX_TECHNICAL
        ).count() == 0

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_get_or_create_no_duplicates(self, mock_get):
        """Повторный запуск → дубль SeoTask не создаётся (get_or_create)."""
        mock_get.return_value = MagicMock(status_code=500)
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        from agents.models import SeoTask

        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        url = "https://formulatela.ru/uslugi/broken/"

        # Первый запуск
        watchdog.check_service_pages([url])
        assert SeoTask.objects.filter(task_type=SeoTask.TYPE_FIX_TECHNICAL).count() == 1

        # Второй запуск — дубль не создаётся
        watchdog.check_service_pages([url])
        assert SeoTask.objects.filter(task_type=SeoTask.TYPE_FIX_TECHNICAL).count() == 1

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_returns_all_results_mixed(self, mock_get):
        """Возвращает все URL — и ОК, и с ошибками."""
        mock_get.side_effect = [
            MagicMock(status_code=200),
            MagicMock(status_code=404),
            MagicMock(status_code=200),
        ]
        from agents.integrations.site_crawler import TechnicalSEOWatchdog

        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        results = watchdog.check_service_pages([
            "https://formulatela.ru/uslugi/a/",
            "https://formulatela.ru/uslugi/b/",
            "https://formulatela.ru/uslugi/c/",
        ])

        assert len(results) == 3
        ok = [r for r in results if not r["issue"]]
        err = [r for r in results if r["issue"]]
        assert len(ok) == 2
        assert len(err) == 1

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_empty_url_list_returns_empty(self, mock_get):
        """Пустой список URL → пустой результат, нет HTTP-запросов."""
        from agents.integrations.site_crawler import TechnicalSEOWatchdog

        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        results = watchdog.check_service_pages([])

        assert results == []
        mock_get.assert_not_called()


class TestCheckSitemap:

    SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://formulatela.ru/</loc></url>
  <url><loc>https://formulatela.ru/uslugi/massazh-spiny/</loc></url>
  <url><loc>https://formulatela.ru/uslugi/klassicheskij-massazh/</loc></url>
  <url><loc>https://formulatela.ru/contacts/</loc></url>
</urlset>"""

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_missing_from_sitemap(self, mock_get):
        """Страница есть в БД, нет в sitemap → попадает в missing_from_sitemap."""
        mock_get.return_value = MagicMock(
            ok=True, content=self.SITEMAP_XML.encode()
        )
        # Услуга есть в БД, но нет в sitemap
        baker.make("services_app.Service", slug="lazernaya-epilyatsiya", is_active=True)
        # Услуга есть и в БД, и в sitemap
        baker.make("services_app.Service", slug="massazh-spiny", is_active=True)

        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog.check_sitemap()

        assert result["sitemap_available"] is True
        assert "https://formulatela.ru/uslugi/lazernaya-epilyatsiya/" in result["missing_from_sitemap"]
        assert "https://formulatela.ru/uslugi/massazh-spiny/" not in result["missing_from_sitemap"]

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_extra_in_sitemap(self, mock_get):
        """URL есть в sitemap, но услуга удалена из БД → extra_in_sitemap."""
        mock_get.return_value = MagicMock(
            ok=True, content=self.SITEMAP_XML.encode()
        )
        # В БД только одна услуга — massazh-spiny
        # klassicheskij-massazh есть в sitemap, но не в БД
        baker.make("services_app.Service", slug="massazh-spiny", is_active=True)

        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog.check_sitemap()

        assert "https://formulatela.ru/uslugi/klassicheskij-massazh/" in result["extra_in_sitemap"]

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_perfect_match(self, mock_get):
        """Все URL совпадают → пустые missing и extra."""
        mock_get.return_value = MagicMock(
            ok=True, content=self.SITEMAP_XML.encode()
        )
        baker.make("services_app.Service", slug="massazh-spiny", is_active=True)
        baker.make("services_app.Service", slug="klassicheskij-massazh", is_active=True)

        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog.check_sitemap()

        assert result["missing_from_sitemap"] == []
        assert result["extra_in_sitemap"] == []
        assert result["sitemap_available"] is True

    @patch("agents.integrations.site_crawler.requests.get")
    def test_sitemap_unavailable_404(self, mock_get):
        """Sitemap вернул 404 → sitemap_available=False, error заполнен."""
        mock_get.return_value = MagicMock(ok=False, status_code=404)
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog.check_sitemap()
        assert result["sitemap_available"] is False
        assert "404" in result["error"]

    @patch("agents.integrations.site_crawler.requests.get")
    def test_sitemap_network_error(self, mock_get):
        """Сетевая ошибка → sitemap_available=False, error заполнен."""
        import requests as req_lib
        mock_get.side_effect = req_lib.ConnectionError("refused")
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog.check_sitemap()
        assert result["sitemap_available"] is False
        assert result["error"] != ""

    @patch("agents.integrations.site_crawler.requests.get")
    def test_sitemap_invalid_xml(self, mock_get):
        """Невалидный XML → sitemap_available=True (загружен), error=ParseError."""
        mock_get.return_value = MagicMock(ok=True, content=b"<broken xml")
        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog.check_sitemap()
        assert result["sitemap_available"] is True
        assert "XML parse error" in result["error"]

    @pytest.mark.django_db
    @patch("agents.integrations.site_crawler.requests.get")
    def test_sitemap_counts_correct(self, mock_get):
        """Счётчики sitemap_total и service_urls_in_db корректны."""
        mock_get.return_value = MagicMock(
            ok=True, content=self.SITEMAP_XML.encode()
        )
        baker.make("services_app.Service", slug="massazh-spiny", is_active=True)

        from agents.integrations.site_crawler import TechnicalSEOWatchdog
        watchdog = TechnicalSEOWatchdog(base_url="https://formulatela.ru")
        result = watchdog.check_sitemap()

        assert result["sitemap_total"] == 4    # 4 тега <loc> в тестовом XML
        assert result["service_urls_in_db"] == 1  # 1 активная услуга в БД
