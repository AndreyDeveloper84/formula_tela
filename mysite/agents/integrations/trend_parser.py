"""
Парсеры трендов: Яндекс подсказки + VK группы.

YandexSuggestClient — бесплатный API автодополнения Яндекса (без авторизации).
VkSocialClient — парсинг публичных постов из VK-групп через VK API wall.get.

Используется TrendScoutAgent для еженедельного сбора рыночных трендов.
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class TrendParserError(Exception):
    pass


class YandexSuggestClient:
    """Парсер подсказок Яндекса (бесплатный, без авторизации)."""

    SUGGEST_URL = "https://suggest-ya.cgi.yandex.net/suggest-ya.cgi"

    def __init__(self, proxy_url: str = ""):
        self.proxy_url = proxy_url

    @classmethod
    def from_settings(cls) -> "YandexSuggestClient":
        proxy = getattr(settings, "OPENAI_PROXY", "")
        return cls(proxy_url=proxy)

    def _get_proxies(self) -> dict | None:
        if self.proxy_url:
            return {"https": self.proxy_url, "http": self.proxy_url}
        return None

    def get_suggestions(self, query: str) -> list[str]:
        """Возвращает список подсказок для запроса."""
        params = {
            "part": query,
            "uil": "ru",
            "sn": 10,
            "srv": "morda_ru_desktop",
            "wiz": "TrWth",
        }
        try:
            r = requests.get(
                self.SUGGEST_URL,
                params=params,
                proxies=self._get_proxies(),
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("YandexSuggest: ошибка для '%s' — %s", query, exc)
            return []

        try:
            data = r.json()
            # Формат ответа: [query, [suggestion1, suggestion2, ...], ...]
            if isinstance(data, list) and len(data) >= 2:
                return [s for s in data[1] if isinstance(s, str)]
        except (json.JSONDecodeError, IndexError, TypeError):
            logger.warning(
                "YandexSuggest: не удалось распарсить ответ для '%s'", query
            )
        return []

    def collect_trends(self, seed_queries: list[str]) -> list[dict]:
        """
        Собирает подсказки по списку seed-запросов.
        Возвращает: [{"seed": str, "suggestions": [str, ...]}]
        """
        results = []
        for query in seed_queries:
            suggestions = self.get_suggestions(query)
            results.append({"seed": query, "suggestions": suggestions})
            time.sleep(0.3)  # вежливая задержка между запросами
        return results


class VkSocialError(TrendParserError):
    pass


class VkSocialClient:
    """Парсер публичных постов из VK-групп через VK API wall.get."""

    API_URL = "https://api.vk.com/method"
    API_VERSION = "5.199"

    def __init__(self, service_token: str, proxy_url: str = ""):
        self.service_token = service_token
        self.proxy_url = proxy_url

    @classmethod
    def from_settings(cls) -> "VkSocialClient":
        token = getattr(settings, "VK_SERVICE_TOKEN", "")
        proxy = getattr(settings, "OPENAI_PROXY", "")
        if not token:
            raise VkSocialError("VK_SERVICE_TOKEN не настроен в .env")
        return cls(service_token=token, proxy_url=proxy)

    def _get_proxies(self) -> dict | None:
        if self.proxy_url:
            return {"https": self.proxy_url, "http": self.proxy_url}
        return None

    def get_wall_posts(self, group_id: str, count: int = 30) -> list[dict]:
        """
        Получает последние посты из группы.
        Возвращает: [{"text", "likes", "comments", "reposts", "views", "date"}]
        """
        params = {
            "owner_id": f"-{group_id}",
            "count": count,
            "filter": "all",
            "access_token": self.service_token,
            "v": self.API_VERSION,
        }
        try:
            r = requests.get(
                f"{self.API_URL}/wall.get",
                params=params,
                proxies=self._get_proxies(),
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as exc:
            logger.warning("VK wall.get: ошибка для группы %s — %s", group_id, exc)
            return []

        if "error" in data:
            logger.warning(
                "VK API error для группы %s: %s",
                group_id,
                data["error"].get("error_msg", "unknown"),
            )
            return []

        posts = []
        for item in data.get("response", {}).get("items", []):
            text = item.get("text", "").strip()
            if not text or len(text) < 20:
                continue  # пропускаем репосты без текста и короткие
            posts.append({
                "text": text[:500],  # ограничиваем длину
                "likes": item.get("likes", {}).get("count", 0),
                "comments": item.get("comments", {}).get("count", 0),
                "reposts": item.get("reposts", {}).get("count", 0),
                "views": item.get("views", {}).get("count", 0),
                "date": datetime.fromtimestamp(
                    item.get("date", 0), tz=timezone.utc
                ).strftime("%Y-%m-%d"),
            })
        return posts

    def collect_top_posts(
        self, group_ids: list[str], days: int = 14, top_n: int = 15
    ) -> list[dict]:
        """
        Собирает топ-посты (по engagement) из списка групп за последние N дней.
        Возвращает отсортированный список по engagement_score.
        """
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime(
            "%Y-%m-%d"
        )
        all_posts = []

        for group_id in group_ids:
            posts = self.get_wall_posts(group_id)
            for post in posts:
                if post["date"] < cutoff:
                    continue
                post["group_id"] = group_id
                post["engagement"] = (
                    post["likes"] + post["comments"] * 3 + post["reposts"] * 2
                )
                all_posts.append(post)
            time.sleep(0.5)  # VK rate limit

        all_posts.sort(key=lambda p: p["engagement"], reverse=True)
        return all_posts[:top_n]
