"""
TechnicalSEOWatchdog — технический crawler для SEO-мониторинга.

Проверяет:
- доступность страниц услуг (404/500 → создаёт SeoTask)
- sitemap.xml — соответствие страниц в карте сайта и активным услугам

Запускается вручную через management-команду check_crawler,
или может встраиваться в недельный pipeline SEOLandingAgent.

Не вызывает сторонних API — работает только с собственным сайтом и БД.
"""
import logging
import xml.etree.ElementTree as ET

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class TechnicalSEOError(Exception):
    pass


class TechnicalSEOWatchdog:
    """
    Технический watchdog: обходит страницы сайта, выявляет проблемы,
    создаёт SeoTask при нахождении битых страниц.

    Использование:
        watchdog = TechnicalSEOWatchdog.from_settings()
        urls = watchdog.get_all_service_urls()
        issues = watchdog.check_service_pages(urls)
        sitemap_diff = watchdog.check_sitemap()
    """

    # HTTP-коды, требующие создания SeoTask
    ERROR_STATUS_CODES = {404, 500, 502, 503}

    def __init__(self, base_url: str, timeout: int = 10):
        """
        Args:
            base_url: базовый URL сайта БЕЗ trailing slash,
                      например "https://formulatela.ru"
            timeout:  таймаут HTTP-запроса в секундах (по умолчанию 10)
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_settings(cls) -> "TechnicalSEOWatchdog":
        """
        Создаёт экземпляр из Django settings.
        Требует: SITE_BASE_URL в settings (или .env).
        """
        base_url = getattr(settings, "SITE_BASE_URL", "")
        if not base_url:
            raise TechnicalSEOError(
                "SITE_BASE_URL должен быть настроен в .env "
                "(например: https://formulatela.ru)"
            )
        return cls(base_url=base_url)

    def get_all_service_urls(self) -> list[str]:
        """
        Возвращает список полных URL всех активных страниц услуг.

        Формирует URL по паттерну: {base_url}/uslugi/{service.slug}/
        Соответствует URL-паттерну в urls.py: /uslugi/<slug>/

        Услуги без slug пропускаются (slug обязателен для SEO-страниц).

        Returns:
            ["https://formulatela.ru/uslugi/klassicheskij-massazh/", ...]
        """
        from services_app.models import Service

        urls = []
        services = Service.objects.active().only("slug", "name")
        for svc in services:
            if not svc.slug:
                logger.warning(
                    "TechnicalSEOWatchdog: услуга '%s' (id=%s) без slug — пропущена",
                    svc.name, svc.pk,
                )
                continue
            url = f"{self.base_url}/uslugi/{svc.slug}/"
            urls.append(url)

        logger.info(
            "TechnicalSEOWatchdog.get_all_service_urls: %d активных URL", len(urls)
        )
        return urls

    def _check_url(self, url: str) -> dict:
        """
        Выполняет GET-запрос к URL, возвращает результат проверки.

        Returns:
            {"url": str, "status_code": int, "issue": str}
            issue == "" если страница доступна (2xx/3xx)
        """
        try:
            resp = requests.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; FormulaTelaSEOBot/1.0)"
                    )
                },
            )
            status = resp.status_code
            if status in self.ERROR_STATUS_CODES:
                issue = f"HTTP {status}"
            elif status >= 400:
                issue = f"HTTP {status}"
            else:
                issue = ""
            return {"url": url, "status_code": status, "issue": issue}
        except requests.Timeout:
            return {"url": url, "status_code": 0, "issue": "timeout"}
        except requests.ConnectionError as exc:
            return {"url": url, "status_code": 0, "issue": f"connection_error: {exc}"}
        except requests.RequestException as exc:
            return {"url": url, "status_code": 0, "issue": f"request_error: {exc}"}

    def check_service_pages(self, url_list: list[str]) -> list[dict]:
        """
        Проверяет каждый URL из списка. При обнаружении ошибки (4xx/5xx/timeout)
        создаёт SeoTask с task_type='fix_technical', priority='high'.

        get_or_create по (task_type, target_url, status='open') —
        чтобы не плодить дубли при повторных запусках.

        Args:
            url_list: список полных URL для проверки

        Returns:
            [
                {"url": "https://...", "status_code": 200, "issue": ""},
                {"url": "https://...", "status_code": 404, "issue": "HTTP 404"},
                ...
            ]
            Возвращает ВСЕ URL — и ОК, и с ошибками.
        """
        from agents.models import SeoTask

        results = []
        errors_found = 0

        for url in url_list:
            result = self._check_url(url)
            results.append(result)

            if result["issue"]:
                errors_found += 1
                # Относительный путь для хранения в SeoTask
                relative_url = url.replace(self.base_url, "")

                task, created = SeoTask.objects.get_or_create(
                    task_type=SeoTask.TYPE_FIX_TECHNICAL,
                    target_url=relative_url,
                    status=SeoTask.STATUS_OPEN,
                    defaults={
                        "title": f"Технический баг: {result['issue']} на {relative_url}",
                        "description": (
                            f"TechnicalSEOWatchdog обнаружил ошибку {result['issue']} "
                            f"при проверке страницы {url}. "
                            f"Статус: {result['status_code']}."
                        ),
                        "priority": SeoTask.PRIORITY_HIGH,
                        "payload": {
                            "status_code": result["status_code"],
                            "issue": result["issue"],
                            "full_url": url,
                        },
                    },
                )
                if created:
                    logger.warning(
                        "TechnicalSEOWatchdog: создана SeoTask #%s — %s на %s",
                        task.pk, result["issue"], url,
                    )
                else:
                    logger.info(
                        "TechnicalSEOWatchdog: SeoTask #%s уже существует для %s",
                        task.pk, url,
                    )

        logger.info(
            "TechnicalSEOWatchdog.check_service_pages: проверено %d URL, "
            "ошибок %d",
            len(results), errors_found,
        )
        return results

    def check_sitemap(self) -> dict:
        """
        Загружает sitemap.xml и сравнивает с активными услугами в БД.

        Алгоритм:
        1. GET {base_url}/sitemap.xml
        2. Парсит XML (namespace sitemap: http://www.sitemaps.org/schemas/sitemap/0.9)
        3. Извлекает все <loc> теги
        4. Формирует ожидаемые URL из Service.objects.filter(is_active=True)
        5. Сравнивает два множества

        Returns:
            {
                "sitemap_url": str,          # URL из которого читали
                "sitemap_total": int,        # всего URL в sitemap
                "service_urls_in_db": int,   # активных услуг в БД
                "missing_from_sitemap": [],  # есть в БД, нет в sitemap
                "extra_in_sitemap": [],      # есть в sitemap, нет в БД
                "sitemap_available": bool,   # False если sitemap недоступен
                "error": str,               # "" если всё OK
            }
        """
        from services_app.models import Service

        sitemap_url = f"{self.base_url}/sitemap.xml"
        result = {
            "sitemap_url": sitemap_url,
            "sitemap_total": 0,
            "service_urls_in_db": 0,
            "missing_from_sitemap": [],
            "extra_in_sitemap": [],
            "sitemap_available": False,
            "error": "",
        }

        # --- Шаг 1: загружаем sitemap ---
        try:
            resp = requests.get(sitemap_url, timeout=self.timeout)
            if not resp.ok:
                result["error"] = f"HTTP {resp.status_code}"
                logger.warning(
                    "TechnicalSEOWatchdog.check_sitemap: %s вернул %s",
                    sitemap_url, resp.status_code,
                )
                return result
        except requests.RequestException as exc:
            result["error"] = str(exc)
            logger.warning(
                "TechnicalSEOWatchdog.check_sitemap: ошибка загрузки %s — %s",
                sitemap_url, exc,
            )
            return result

        result["sitemap_available"] = True

        # --- Шаг 2: парсим XML ---
        # Sitemap namespace: http://www.sitemaps.org/schemas/sitemap/0.9
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            result["error"] = f"XML parse error: {exc}"
            logger.warning(
                "TechnicalSEOWatchdog.check_sitemap: ошибка парсинга XML — %s", exc
            )
            return result

        # Sitemap может быть urlset (один файл) или sitemapindex (индекс)
        # Для простоты обрабатываем urlset напрямую
        sitemap_locs = set()
        for loc_el in root.findall(".//sm:loc", ns):
            if loc_el.text:
                sitemap_locs.add(loc_el.text.strip())

        # Fallback без namespace (если sitemap сгенерирован без xmlns)
        if not sitemap_locs:
            for loc_el in root.findall(".//loc"):
                if loc_el.text:
                    sitemap_locs.add(loc_el.text.strip())

        result["sitemap_total"] = len(sitemap_locs)

        # --- Шаг 3: строим ожидаемые URL из БД ---
        db_service_urls = set()
        services = Service.objects.active().only("slug")
        for svc in services:
            if svc.slug:
                db_service_urls.add(f"{self.base_url}/uslugi/{svc.slug}/")

        result["service_urls_in_db"] = len(db_service_urls)

        # --- Шаг 4: сравниваем ---
        # Только URLs страниц услуг (/uslugi/) из sitemap
        sitemap_service_urls = {
            url for url in sitemap_locs
            if "/uslugi/" in url
        }

        missing = sorted(db_service_urls - sitemap_service_urls)
        extra = sorted(sitemap_service_urls - db_service_urls)

        result["missing_from_sitemap"] = missing
        result["extra_in_sitemap"] = extra

        logger.info(
            "TechnicalSEOWatchdog.check_sitemap: "
            "sitemap=%d URLs (из них /uslugi/=%d), "
            "в БД=%d, отсутствуют в sitemap=%d, лишние в sitemap=%d",
            len(sitemap_locs), len(sitemap_service_urls),
            len(db_service_urls), len(missing), len(extra),
        )
        return result
