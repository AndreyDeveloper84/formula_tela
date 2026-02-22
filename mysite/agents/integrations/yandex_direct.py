"""
Яндекс.Директ Reports API v5 client.
Docs: https://yandex.ru/dev/direct/doc/reports/
"""
import csv
import io
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class YandexDirectError(Exception):
    pass


class YandexDirectClient:
    BASE_URL = "https://api.direct.yandex.com/json/v5/reports"

    def __init__(self, token: str, client_login: str):
        self.token = token
        self.client_login = client_login

    @classmethod
    def from_settings(cls) -> "YandexDirectClient":
        """Instantiate from Django settings. Raises YandexDirectError if credentials missing."""
        token = getattr(settings, "YANDEX_DIRECT_TOKEN", "")
        login = getattr(settings, "YANDEX_DIRECT_CLIENT_LOGIN", "")
        if not token or not login:
            raise YandexDirectError(
                "YANDEX_DIRECT_TOKEN и YANDEX_DIRECT_CLIENT_LOGIN должны быть настроены в .env"
            )
        return cls(token=token, client_login=login)

    def _request(self, body: dict, max_retries: int = 3) -> str:
        """
        POST to Директ Reports API.
        Handles 201/202 (report queued) with polling.
        Returns raw TSV string on 200.
        """
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Client-Login": self.client_login,
            "Accept-Language": "ru",
            "processingMode": "auto",
            "returnMoneyInMicros": "false",
            "skipReportHeader": "true",
            "skipColumnHeader": "false",
            "skipReportSummary": "true",
        }
        for attempt in range(max_retries):
            try:
                r = requests.post(self.BASE_URL, json=body, headers=headers, timeout=30)
                if r.status_code == 200:
                    return r.text
                elif r.status_code in (201, 202):
                    retry_in = int(r.headers.get("retryIn", "5"))
                    logger.info(
                        "YandexDirectClient: отчёт готовится, ждём %s сек. (попытка %d/%d)",
                        retry_in, attempt + 1, max_retries,
                    )
                    time.sleep(min(retry_in, 30))
                    continue
                else:
                    raise YandexDirectError(f"HTTP {r.status_code}: {r.text[:300]}")
            except requests.RequestException as exc:
                raise YandexDirectError(f"Network error: {exc}") from exc
        raise YandexDirectError("Директ: отчёт не готов после всех попыток")

    def get_campaign_stats(self, date_from: str, date_to: str) -> dict:
        """
        Fetch campaign performance for a date range.

        Args:
            date_from: "YYYY-MM-DD"
            date_to:   "YYYY-MM-DD"

        Returns:
            {clicks, impressions, cost, ctr, campaigns_count}
        """
        body = {
            "params": {
                "SelectionCriteria": {
                    "DateFrom": date_from,
                    "DateTo": date_to,
                },
                "FieldNames": ["CampaignName", "Clicks", "Impressions", "Cost", "Ctr"],
                "ReportName": f"salon_stats_{date_from}_{date_to}",
                "ReportType": "CAMPAIGN_PERFORMANCE_REPORT",
                "DateRangeType": "CUSTOM_DATE",
                "Format": "TSV",
                "IncludeVAT": "YES",
                "IncludeDiscount": "NO",
            }
        }
        raw_tsv = self._request(body)

        clicks_total = 0
        impressions_total = 0
        cost_total = 0.0
        campaigns: set[str] = set()

        reader = csv.DictReader(io.StringIO(raw_tsv), delimiter="\t")
        for row in reader:
            campaign_name = row.get("CampaignName", "").strip()
            if campaign_name:
                campaigns.add(campaign_name)
            clicks_total += int(row.get("Clicks", 0) or 0)
            impressions_total += int(row.get("Impressions", 0) or 0)
            cost_total += float(row.get("Cost", 0) or 0)

        ctr = round(clicks_total / impressions_total * 100, 2) if impressions_total else 0.0

        return {
            "clicks":           clicks_total,
            "impressions":      impressions_total,
            "cost":             round(cost_total, 2),
            "ctr":              ctr,
            "campaigns_count":  len(campaigns),
        }
