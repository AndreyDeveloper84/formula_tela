"""
Яндекс.Вебмастер API v4 client.
Docs: https://yandex.ru/dev/webmaster/doc/dg/reference/host-id.html

Используется для получения:
- топ страниц по кликам/показам/CTR/позиции
- топ поисковых запросов
- списка верифицированных сайтов

Аутентификация: OAuth-токен (https://oauth.yandex.ru/)
"""
import logging
from datetime import date

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class YandexWebmasterError(Exception):
    pass


def _extract_indicators(item: dict) -> dict:
    """Yandex Webmaster отдаёт indicators как dict {"TOTAL_SHOWS": 3.0, ...}.
    Исторически код ожидал list [{"query_indicator": "TOTAL_SHOWS", "value": 3.0}, ...] —
    поддерживаем оба варианта для устойчивости к изменению формата API."""
    raw = item.get("indicators") or {}
    if isinstance(raw, list):
        return {ind.get("query_indicator"): ind.get("value", 0) for ind in raw if isinstance(ind, dict)}
    return raw


class YandexWebmasterClient:
    BASE_URL = "https://api.webmaster.yandex.net/v4"

    def __init__(self, token: str, user_id: str = "", host_id: str = ""):
        self.token = token
        self._user_id = str(user_id) if user_id else ""
        self.host_id = host_id

    @classmethod
    def from_settings(cls) -> "YandexWebmasterClient":
        """
        Создаёт клиент из Django settings.
        Обязательно: YANDEX_WEBMASTER_TOKEN, YANDEX_WEBMASTER_HOST_ID.
        Опционально: YANDEX_WEBMASTER_USER_ID (авто-получается если не задан).
        Raises YandexWebmasterError если токен или host_id не настроены.
        """
        token = getattr(settings, "YANDEX_WEBMASTER_TOKEN", "")
        host_id = getattr(settings, "YANDEX_WEBMASTER_HOST_ID", "")
        user_id = getattr(settings, "YANDEX_WEBMASTER_USER_ID", "")
        if not token:
            raise YandexWebmasterError(
                "YANDEX_WEBMASTER_TOKEN должен быть настроен в .env"
            )
        if not host_id:
            raise YandexWebmasterError(
                "YANDEX_WEBMASTER_HOST_ID должен быть настроен в .env "
                "(формат: https:yourdomain.ru:443)"
            )
        return cls(token=token, user_id=user_id, host_id=host_id)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """
        Выполняет запрос к API Вебмастера.
        path: относительный путь, например '/user/12345/hosts/'
        """
        url = self.BASE_URL + path
        headers = {"Authorization": f"OAuth {self.token}"}
        kwargs.setdefault("timeout", 30)
        proxy_url = getattr(settings, "OPENAI_PROXY", "")
        if proxy_url:
            kwargs.setdefault("proxies", {"https": proxy_url, "http": proxy_url})
        try:
            r = requests.request(method, url, headers=headers, **kwargs)
            if not r.ok:
                raise YandexWebmasterError(
                    f"HTTP {r.status_code}: {r.text[:300]}"
                )
            try:
                return r.json()
            except (ValueError, Exception) as exc:
                raise YandexWebmasterError(
                    f"Invalid JSON response: {r.text[:200]}"
                ) from exc
        except requests.RequestException as exc:
            raise YandexWebmasterError(f"Network error: {exc}") from exc

    def get_user_id(self) -> str:
        """
        Получает числовой ID Яндекс-аккаунта (user_id).
        Кешируется в self._user_id.
        GET /user/
        """
        if self._user_id:
            return self._user_id
        data = self._request("GET", "/user/")
        uid = str(data.get("user_id", ""))
        if not uid:
            raise YandexWebmasterError(
                "Не удалось получить user_id из ответа API"
            )
        self._user_id = uid
        return self._user_id

    def list_hosts(self) -> list[dict]:
        """
        Возвращает список верифицированных сайтов в аккаунте.
        GET /user/{user_id}/hosts/
        Каждый элемент: {host_id, ascii_host_url, unicode_host_url, verified}
        """
        uid = self.get_user_id()
        data = self._request("GET", f"/user/{uid}/hosts/")
        hosts = data.get("hosts", [])
        return [
            {
                "host_id": h.get("host_id", ""),
                "url": h.get("unicode_host_url") or h.get("ascii_host_url", ""),
                "verified": h.get("verified") is True
                or h.get("verified_state") == "VERIFIED",
            }
            for h in hosts
        ]

    def get_top_queries(
        self,
        date_from: str,
        date_to: str,
        limit: int = 100,
    ) -> list[dict]:
        """
        Возвращает топ поисковых запросов за период.
        GET /user/{user_id}/hosts/{host_id}/search-queries/popular

        Параметры date_from/date_to: "YYYY-MM-DD".
        Возвращает: [{query, clicks, impressions, ctr, avg_position}, ...]
        avg_position — среднее значение (чем меньше, тем выше в выдаче).
        """
        uid = self.get_user_id()
        path = f"/user/{uid}/hosts/{self.host_id}/search-queries/popular"
        try:
            data = self._request(
                "GET",
                path,
                params={
                    # API v4 хочет повторяющийся параметр
                    # ?query_indicator=TOTAL_SHOWS&query_indicator=TOTAL_CLICKS&...
                    # Список в requests разворачивается именно так.
                    # Строка через запятую приводит к HTTP 400 (enum not found).
                    "query_indicator": [
                        "TOTAL_SHOWS",
                        "TOTAL_CLICKS",
                        "AVG_SHOW_POSITION",
                        "AVG_CLICK_POSITION",
                    ],
                    "order_by": "TOTAL_SHOWS",
                    "date_from": date_from,
                    "date_to": date_to,
                    "count_indicators": limit,
                },
            )
        except YandexWebmasterError:
            raise

        queries = []
        for item in data.get("queries", []):
            indicators = _extract_indicators(item)
            clicks = int(indicators.get("TOTAL_CLICKS", 0) or 0)
            impressions = int(indicators.get("TOTAL_SHOWS", 0) or 0)
            avg_pos = float(indicators.get("AVG_SHOW_POSITION", 0) or 0)
            ctr = round(clicks / impressions, 4) if impressions > 0 else 0.0
            queries.append({
                "query": item.get("query_text", ""),
                "clicks": clicks,
                "impressions": impressions,
                "ctr": ctr,
                "avg_position": avg_pos,
            })
        return queries

    def get_top_pages(
        self,
        date_from: str,
        date_to: str,
        limit: int = 100,
    ) -> list[dict]:
        """
        Возвращает топ страниц по кликам за период.
        GET /user/{user_id}/hosts/{host_id}/search-queries/popular  с group_by=URL

        Параметры date_from/date_to: "YYYY-MM-DD".
        Возвращает: [{url, clicks, impressions, ctr, avg_position}, ...]
        """
        uid = self.get_user_id()
        path = f"/user/{uid}/hosts/{self.host_id}/search-queries/popular"
        try:
            data = self._request(
                "GET",
                path,
                params={
                    # API v4 хочет повторяющийся параметр
                    # ?query_indicator=TOTAL_SHOWS&query_indicator=TOTAL_CLICKS&...
                    # Список в requests разворачивается именно так.
                    # Строка через запятую приводит к HTTP 400 (enum not found).
                    "query_indicator": [
                        "TOTAL_SHOWS",
                        "TOTAL_CLICKS",
                        "AVG_SHOW_POSITION",
                        "AVG_CLICK_POSITION",
                    ],
                    "order_by": "TOTAL_SHOWS",
                    "date_from": date_from,
                    "date_to": date_to,
                    "count_indicators": limit,
                    "group_by": "URL",
                },
            )
        except YandexWebmasterError:
            raise

        pages = []
        for item in data.get("queries", []):
            indicators = _extract_indicators(item)
            clicks = int(indicators.get("TOTAL_CLICKS", 0) or 0)
            impressions = int(indicators.get("TOTAL_SHOWS", 0) or 0)
            avg_pos = float(indicators.get("AVG_SHOW_POSITION", 0) or 0)
            ctr = round(clicks / impressions, 4) if impressions > 0 else 0.0

            # URL может быть в поле query_text или url в зависимости от API версии
            url = item.get("url") or item.get("query_text", "")
            if not url:
                continue
            pages.append({
                "url": url,
                "clicks": clicks,
                "impressions": impressions,
                "ctr": ctr,
                "avg_position": avg_pos,
            })
        return pages

    def get_query_stats(
        self,
        date_from: str,
        date_to: str,
        limit: int = 500,
    ) -> list[dict]:
        """
        Топ поисковых запросов за период с расширенным лимитом.
        Используется SEO-агентом для сопоставления запросов с кластерами.

        Параметры date_from/date_to: "YYYY-MM-DD".
        Возвращает: [{query, clicks, impressions, ctr, avg_position}, ...]
        При ошибке API — логирует warning, возвращает [].
        """
        try:
            return self.get_top_queries(date_from, date_to, limit=limit)
        except YandexWebmasterError as exc:
            logger.exception(
                "YandexWebmasterClient.get_query_stats: ошибка — %s", exc
            )
            return []

    def get_page_stats(
        self,
        date_from: str,
        date_to: str,
        limit: int = 100,
    ) -> list[dict]:
        """
        Топ страниц по кликам за период.
        Используется SEO-агентом для анализа эффективности страниц.

        Параметры date_from/date_to: "YYYY-MM-DD".
        Возвращает: [{url, clicks, impressions, ctr, avg_position}, ...]
        При ошибке API — логирует warning, возвращает [].
        """
        try:
            return self.get_top_pages(date_from, date_to, limit=limit)
        except YandexWebmasterError as exc:
            logger.exception(
                "YandexWebmasterClient.get_page_stats: ошибка — %s", exc
            )
            return []
