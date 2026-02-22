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
        try:
            r = requests.get(self.BASE_URL, params=params, headers=headers, timeout=15)
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
        """
        # --- Aggregated totals ---
        params = {
            "id": self.counter_id,
            "metrics": "ym:s:visits,ym:s:bounceRate,ym:s:goalReachesAny,ym:s:pageDepth",
            "date1": date1,
            "date2": date2,
        }
        data = self._request(params)
        totals = data.get("totals", [])

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
            "goal_reaches": int(totals[2]) if len(totals) > 2 else 0,
            "page_depth":   round(float(totals[3]), 2) if len(totals) > 3 else 0.0,
            "top_sources":  top_sources,
        }
