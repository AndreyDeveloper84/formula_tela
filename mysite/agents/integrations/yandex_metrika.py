"""
Яндекс.Метрика Reporting API v1 client.
Docs: https://yandex.ru/dev/metrika/doc/api2/api_v1/data.html
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class YandexMetrikaError(Exception):
    pass


class YandexMetrikaClient:
    BASE_URL = "https://api-metrika.yandex.net/stat/v1/data"

    def __init__(self, token: str, counter_id: str):
        self.token = token
        self.counter_id = str(counter_id)

    @classmethod
    def from_settings(cls) -> "YandexMetrikaClient":
        """Instantiate from Django settings. Raises YandexMetrikaError if credentials missing."""
        token = getattr(settings, "YANDEX_METRIKA_TOKEN", "")
        counter_id = getattr(settings, "YANDEX_METRIKA_COUNTER_ID", "")
        if not token or not counter_id:
            raise YandexMetrikaError(
                "YANDEX_METRIKA_TOKEN и YANDEX_METRIKA_COUNTER_ID должны быть настроены в .env"
            )
        return cls(token=token, counter_id=counter_id)

    def _request(self, params: dict) -> dict:
        """Raw GET to Metrika stat API with OAuth header."""
        headers = {"Authorization": f"OAuth {self.token}"}
        kwargs = {"timeout": 15}
        proxy_url = getattr(settings, "OPENAI_PROXY", "")
        if proxy_url:
            kwargs["proxies"] = {"https": proxy_url, "http": proxy_url}
        try:
            r = requests.get(self.BASE_URL, params=params, headers=headers, **kwargs)
            if not r.ok:
                raise YandexMetrikaError(f"HTTP {r.status_code}: {r.text[:300]}")
            return r.json()
        except requests.RequestException as exc:
            raise YandexMetrikaError(f"Network error: {exc}") from exc

    def get_summary(self, date1: str, date2: str) -> dict:
        """
        Fetch aggregated metrics for a date range.

        Args:
            date1: start date "YYYY-MM-DD"
            date2: end date   "YYYY-MM-DD"

        Returns:
            {sessions, bounce_rate, goal_reaches, page_depth, top_sources}

        Note: goal_reaches получается отдельным запросом, т.к. Metrika API v1
        не имеет универсальной метрики «любые цели» — нужны конкретные goal IDs.
        При отсутствии целей в счётчике возвращается 0.
        """
        # --- Aggregated totals (3 гарантированно валидные метрики) ---
        params = {
            "id": self.counter_id,
            "metrics": "ym:s:visits,ym:s:bounceRate,ym:s:pageDepth",
            "date1": date1,
            "date2": date2,
        }
        data = self._request(params)
        totals = data.get("totals", [])

        # --- Достижение целей (опционально) ---
        # Используем ym:s:goal_conversions или считаем по всем goals через dimensions
        goal_reaches = 0
        try:
            goal_params = {
                "id": self.counter_id,
                "metrics": "ym:s:visits",
                "dimensions": "ym:s:goal",
                "date1": date1,
                "date2": date2,
                "limit": 1,
            }
            goal_data = self._request(goal_params)
            # Если счётчик имеет цели — суммируем их визиты
            for row in goal_data.get("data", []):
                goal_reaches += int(row["metrics"][0]) if row.get("metrics") else 0
        except Exception as exc:
            logger.debug("YandexMetrikaClient: цели не получены (счётчик может не иметь целей): %s", exc)

        # --- Top traffic sources ---
        top_sources = []
        try:
            src_params = {
                "id": self.counter_id,
                "metrics": "ym:s:visits",
                "dimensions": "ym:s:trafficSource",
                "date1": date1,
                "date2": date2,
                "limit": 5,
                "sort": "-ym:s:visits",
            }
            src_data = self._request(src_params)
            for row in src_data.get("data", [])[:5]:
                top_sources.append({
                    "source": row["dimensions"][0].get("name", "?") if row.get("dimensions") else "?",
                    "visits": int(row["metrics"][0]) if row.get("metrics") else 0,
                })
        except Exception as exc:
            logger.warning("YandexMetrikaClient: не удалось получить источники трафика: %s", exc)

        return {
            "sessions":     int(totals[0]) if len(totals) > 0 else 0,
            "bounce_rate":  round(float(totals[1]), 1) if len(totals) > 1 else 0.0,
            "page_depth":   round(float(totals[2]), 2) if len(totals) > 2 else 0.0,
            "goal_reaches": goal_reaches,
            "top_sources":  top_sources,
        }

    def get_organic_sessions(self, date_from: str, date_to: str) -> dict:
        """
        Возвращает метрики органического трафика (источник = поисковые системы).
        Используется SEO-агентом для оценки SEO-эффективности в целом.

        Args:
            date_from: "YYYY-MM-DD"
            date_to:   "YYYY-MM-DD"

        Returns:
            {
                "sessions":          int,
                "bounce_rate":       float,
                "avg_depth":         float,
                "goal_conversions":  int,
            }
            При любой ошибке API — возвращает нулевой словарь, не бросает исключение.
        """
        try:
            params = {
                "id": self.counter_id,
                "metrics": "ym:s:visits,ym:s:bounceRate,ym:s:pageDepth",
                "dimensions": "ym:s:trafficSource",
                "date1": date_from,
                "date2": date_to,
                "sort": "-ym:s:visits",
                "limit": 10,
            }
            data = self._request(params)

            sessions = 0
            bounce_rate = 0.0
            avg_depth = 0.0

            for row in data.get("data", []):
                dims = row.get("dimensions", [])
                source_name = dims[0].get("name", "").lower() if dims else ""
                if any(kw in source_name for kw in ("поисков", "organic", "search")):
                    metrics = row.get("metrics", [])
                    sessions = int(metrics[0]) if len(metrics) > 0 else 0
                    bounce_rate = round(float(metrics[1]), 1) if len(metrics) > 1 else 0.0
                    avg_depth = round(float(metrics[2]), 2) if len(metrics) > 2 else 0.0
                    break

            goal_conversions = 0
            try:
                goal_params = {
                    "id": self.counter_id,
                    "metrics": "ym:s:visits",
                    "dimensions": "ym:s:trafficSource,ym:s:goal",
                    "date1": date_from,
                    "date2": date_to,
                    "limit": 20,
                }
                goal_data = self._request(goal_params)
                for row in goal_data.get("data", []):
                    dims = row.get("dimensions", [])
                    source_name = dims[0].get("name", "").lower() if dims else ""
                    if any(kw in source_name for kw in ("поисков", "organic", "search")):
                        metrics = row.get("metrics", [])
                        goal_conversions += int(metrics[0]) if metrics else 0
            except Exception as exc:
                logger.debug(
                    "YandexMetrikaClient.get_organic_sessions: цели не получены — %s", exc
                )

            return {
                "sessions": sessions,
                "bounce_rate": bounce_rate,
                "avg_depth": avg_depth,
                "goal_conversions": goal_conversions,
            }

        except YandexMetrikaError as exc:
            logger.warning(
                "YandexMetrikaClient.get_organic_sessions: ошибка API — %s", exc
            )
            return {
                "sessions": 0,
                "bounce_rate": 0.0,
                "avg_depth": 0.0,
                "goal_conversions": 0,
            }

    def get_page_behavior(self, url: str, date_from: str, date_to: str) -> dict:
        """
        Возвращает поведенческие метрики для конкретной страницы.
        Используется SEO-агентом для анализа качества отдельных лендингов.

        Args:
            url:       относительный путь страницы, например "/uslugi/massazh/"
            date_from: "YYYY-MM-DD"
            date_to:   "YYYY-MM-DD"

        Returns:
            {
                "sessions":         int,
                "bounce_rate":      float,
                "time_on_page":     float,
                "goal_conversions": int,
            }
            При любой ошибке API — возвращает нулевой словарь, не бросает исключение.
        """
        try:
            params = {
                "id": self.counter_id,
                "metrics": (
                    "ym:s:visits,"
                    "ym:s:bounceRate,"
                    "ym:s:avgVisitDurationSeconds"
                ),
                "filters": f"ym:s:startURL=='{url}'",
                "date1": date_from,
                "date2": date_to,
            }
            data = self._request(params)
            totals = data.get("totals", [])

            sessions = int(totals[0]) if len(totals) > 0 else 0
            bounce_rate = round(float(totals[1]), 1) if len(totals) > 1 else 0.0
            time_on_page = round(float(totals[2]), 1) if len(totals) > 2 else 0.0

            goal_conversions = 0
            try:
                goal_params = {
                    "id": self.counter_id,
                    "metrics": "ym:s:visits",
                    "dimensions": "ym:s:goal",
                    "filters": f"ym:s:startURL=='{url}'",
                    "date1": date_from,
                    "date2": date_to,
                    "limit": 10,
                }
                goal_data = self._request(goal_params)
                for row in goal_data.get("data", []):
                    metrics = row.get("metrics", [])
                    goal_conversions += int(metrics[0]) if metrics else 0
            except Exception as exc:
                logger.debug(
                    "YandexMetrikaClient.get_page_behavior: цели не получены — %s", exc
                )

            return {
                "sessions": sessions,
                "bounce_rate": bounce_rate,
                "time_on_page": time_on_page,
                "goal_conversions": goal_conversions,
            }

        except YandexMetrikaError as exc:
            logger.warning(
                "YandexMetrikaClient.get_page_behavior: ошибка API — %s", exc
            )
            return {
                "sessions": 0,
                "bounce_rate": 0.0,
                "time_on_page": 0.0,
                "goal_conversions": 0,
            }
