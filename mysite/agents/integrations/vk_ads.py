"""
VK Реклама (ads.vk.com) API v2 client.
Docs: https://ads.vk.com/doc/api/info/

Получает статистику рекламных кампаний (ad_plans) за период.
Используется в AnalyticsBudgetAgent как третий рекламный канал
рядом с Яндекс.Директом.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class VkAdsError(Exception):
    pass


class VkAdsClient:
    BASE_URL = "https://ads.vk.com/api/v2"

    def __init__(self, token: str, account_id: str):
        self.token = token
        # account_id хранится для логирования и будущей поддержки
        # multi-account; Bearer-токен уже скоупирован на аккаунт
        self.account_id = str(account_id)

    @classmethod
    def from_settings(cls) -> "VkAdsClient":
        """
        Создать клиент из Django settings.
        Raises:
            VkAdsError: если VK_ADS_TOKEN или VK_ADS_ACCOUNT_ID не настроены.
        """
        token = getattr(settings, "VK_ADS_TOKEN", "")
        account_id = getattr(settings, "VK_ADS_ACCOUNT_ID", "")
        if not token or not account_id:
            raise VkAdsError(
                "VK_ADS_TOKEN и VK_ADS_ACCOUNT_ID должны быть настроены в .env"
            )
        return cls(token=token, account_id=account_id)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """
        Выполнить аутентифицированный запрос к VK Ads API.
        Args:
            method: HTTP метод ('GET', 'POST', ...)
            path:   путь без базового URL (например 'ad_plans.json')
            **kwargs: передаются в requests.request (params, json, ...)
        Returns:
            Распарсенный JSON-ответ.
        Raises:
            VkAdsError: при HTTP-ошибке или сетевой проблеме.
        """
        url = f"{self.BASE_URL}/{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            r = requests.request(method, url, headers=headers, timeout=15, **kwargs)
            if not r.ok:
                raise VkAdsError(f"HTTP {r.status_code}: {r.text[:300]}")
            return r.json()
        except requests.RequestException as exc:
            raise VkAdsError(f"Network error: {exc}") from exc

    def _get_all_plan_ids(self) -> list:
        """
        Постранично получить все ID рекламных планов (кампаний).
        Returns:
            Список int-ID всех планов в аккаунте.
        """
        plan_ids: list = []
        limit = 50
        offset = 0
        while True:
            data = self._request(
                "GET",
                "ad_plans.json",
                params={"limit": limit, "offset": offset},
            )
            items = data.get("items", [])
            for item in items:
                plan_ids.append(int(item["id"]))
            total = int(data.get("count", 0))
            offset += limit
            if offset >= total or not items:
                break
        return plan_ids

    def get_campaign_stats(self, date_from: str, date_to: str) -> dict:
        """
        Получить агрегированную статистику кампаний за период.

        Args:
            date_from: начало периода "YYYY-MM-DD"
            date_to:   конец периода  "YYYY-MM-DD"

        Returns:
            {
                "impressions":     int,   # показы (VK: base.shows)
                "clicks":          int,   # клики
                "cost":            float, # расход в руб., round(2)
                "ctr":             float, # CTR %, round(2); 0.0 если нет показов
                "campaigns_count": int,   # планов с ненулевой активностью
            }
            Все значения равны 0 / 0.0 если нет планов или данных за период.
        """
        plan_ids = self._get_all_plan_ids()
        if not plan_ids:
            return {
                "impressions": 0,
                "clicks": 0,
                "cost": 0.0,
                "ctr": 0.0,
                "campaigns_count": 0,
            }

        data = self._request(
            "GET",
            "statistics/ad_plans/day.json",
            params={
                "id": ",".join(str(pid) for pid in plan_ids),
                "date_from": date_from,
                "date_to": date_to,
            },
        )

        clicks_total = 0
        impressions_total = 0
        cost_total = 0.0
        active_plan_ids: set = set()

        for item in data.get("items", []):
            plan_id = item.get("id")
            for row in item.get("rows", []):
                base = row.get("base", {})
                c = int(base.get("clicks", 0) or 0)
                s = int(base.get("shows", 0) or 0)
                sp = float(base.get("spent", 0) or 0)
                if c or s or sp:
                    if plan_id is not None:
                        active_plan_ids.add(plan_id)
                clicks_total += c
                impressions_total += s
                cost_total += sp

        ctr = (
            round(clicks_total / impressions_total * 100, 2)
            if impressions_total
            else 0.0
        )

        return {
            "impressions": impressions_total,
            "clicks": clicks_total,
            "cost": round(cost_total, 2),
            "ctr": ctr,
            "campaigns_count": len(active_plan_ids),
        }
