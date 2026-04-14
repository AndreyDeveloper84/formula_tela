"""
TrendScout Agent — еженедельный сбор и анализ трендов рынка массажа/SPA.

Источники:
- Яндекс подсказки (автодополнение поиска)
- VK группы (конкуренты + федеральные тематические)

Результат: TrendSnapshot + AgentReport с JSON-трендами.
Тренды передаются в OfferAgent для генерации актуальных акций.

Расписание: понедельник 07:30 (до остальных агентов).
"""
import json
import logging
from datetime import date

from django.conf import settings
from django.utils import timezone

from agents.agents import get_openai_client
from agents.agents._lifecycle import ensure_task_finalized
from agents.models import AgentReport, AgentTask, TrendSnapshot
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)

DEFAULT_SEED_QUERIES = [
    "массаж пенза",
    "спа пенза",
    "массаж лица",
    "антицеллюлитный массаж",
    "лимфодренажный массаж",
    "массаж спины",
    "подарочный сертификат массаж",
    "массажист пенза",
    "lpg массаж",
    "спа процедуры",
]

SYSTEM_PROMPT = (
    "Ты аналитик трендов в индустрии массажа и SPA в России. "
    "Проанализируй данные из Яндекс-поиска и VK-сообществ. "
    "Выдели 5-10 актуальных трендов, которые салон массажа может использовать "
    "для создания акций и привлечения клиентов.\n\n"
    "Для каждого тренда укажи:\n"
    "- topic: краткое название тренда (2-5 слов)\n"
    "- score: актуальность от 1 до 10\n"
    "- source: откуда тренд (yandex / vk / both)\n"
    "- detail: пояснение и рекомендация для салона (1-2 предложения)\n\n"
    "Ответ строго в формате JSON:\n"
    '{"summary": "краткий обзор трендов (3-5 предложений)", '
    '"trends": [{"topic": "...", "score": N, "source": "...", "detail": "..."}]}'
)


class TrendScoutAgent:
    def gather_yandex_data(self) -> list[dict]:
        """Яндекс подсказки по seed-запросам."""
        from agents.integrations.trend_parser import YandexSuggestClient

        client = YandexSuggestClient.from_settings()
        seed_queries = getattr(settings, "TREND_SEED_QUERIES", DEFAULT_SEED_QUERIES)
        data = client.collect_trends(seed_queries)
        total = sum(len(item["suggestions"]) for item in data)
        logger.info(
            "TrendScout: собрано %d подсказок по %d запросам", total, len(data)
        )
        return data

    def gather_vk_data(self) -> list[dict]:
        """Топ-посты из VK групп за 14 дней."""
        from agents.integrations.trend_parser import VkSocialClient, VkSocialError

        group_ids = getattr(settings, "VK_TREND_GROUP_IDS", [])
        if not group_ids:
            logger.info("TrendScout: VK_TREND_GROUP_IDS не настроены — пропускаем VK")
            return []

        try:
            client = VkSocialClient.from_settings()
        except VkSocialError as exc:
            logger.warning("TrendScout: VK не настроен — %s", exc)
            return []

        data = client.collect_top_posts(group_ids)
        logger.info("TrendScout: собрано %d топ-постов из VK", len(data))
        return data

    def _build_prompt(self, yandex_data: list[dict], vk_data: list[dict]) -> str:
        parts = []

        if yandex_data:
            parts.append("=== ЯНДЕКС ПОДСКАЗКИ ===")
            for item in yandex_data:
                if item["suggestions"]:
                    suggestions = ", ".join(item["suggestions"][:8])
                    parts.append(f'"{item["seed"]}": {suggestions}')

        if vk_data:
            parts.append("\n=== ТОП-ПОСТЫ VK (по вовлечённости) ===")
            for post in vk_data[:10]:
                parts.append(
                    f"[{post['date']}] "
                    f"лайки:{post['likes']} комменты:{post['comments']} "
                    f"репосты:{post['reposts']} просмотры:{post['views']}\n"
                    f"  {post['text'][:200]}"
                )

        parts.append(
            "\n\nПроанализируй эти данные и выдели тренды для салона массажа в Пензе."
        )
        return "\n".join(parts)

    def run(self) -> AgentTask:
        task = AgentTask.objects.create(
            agent_type=AgentTask.TREND_SCOUT,
            status=AgentTask.RUNNING,
            triggered_by="scheduler",
        )
        logger.info("TrendScoutAgent: старт (task_id=%s)", task.pk)
        try:
            # 1. Сбор данных
            yandex_data = self.gather_yandex_data()
            vk_data = self.gather_vk_data()

            if not yandex_data and not vk_data:
                raise TrendParserError("Нет данных ни из Яндекса, ни из VK")

            today = date.today()

            # 2. Сохраняем сырые данные
            if yandex_data:
                TrendSnapshot.objects.update_or_create(
                    source=TrendSnapshot.SOURCE_YANDEX,
                    date=today,
                    defaults={"raw_data": yandex_data},
                )
            if vk_data:
                TrendSnapshot.objects.update_or_create(
                    source=TrendSnapshot.SOURCE_VK,
                    date=today,
                    defaults={"raw_data": vk_data},
                )

            task.input_context = {
                "yandex_queries": len(yandex_data),
                "yandex_total_suggestions": sum(
                    len(item["suggestions"]) for item in yandex_data
                ),
                "vk_posts": len(vk_data),
            }
            task.save(update_fields=["input_context"])

            # 3. GPT-анализ
            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": self._build_prompt(yandex_data, vk_data),
                    },
                ],
                response_format={"type": "json_object"},
                max_tokens=1200,
            )
            raw_text = response.choices[0].message.content.strip()
            task.raw_response = raw_text

            result = json.loads(raw_text)
            summary_text = result.get("summary", "")
            trends = result.get("trends", [])

            # 4. Обновляем снимки анализом
            TrendSnapshot.objects.filter(date=today).update(
                summary=summary_text, trends=trends
            )

            # 5. AgentReport
            AgentReport.objects.create(
                task=task,
                summary=summary_text,
                recommendations=trends,
            )

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            # 6. Telegram
            trends_text = "\n".join(
                f"  {i}. {t['topic']} ({t.get('score', '?')}/10)"
                for i, t in enumerate(trends[:7], 1)
            )
            send_telegram(
                f"\U0001f50d <b>Разведка трендов</b>\n\n"
                f"{summary_text[:500]}\n\n"
                f"<b>Тренды:</b>\n{trends_text}"
            )
            logger.info("TrendScoutAgent: завершён (task_id=%s)", task.pk)

        except Exception as exc:
            logger.exception(
                "TrendScoutAgent: ошибка (task_id=%s) — %s", task.pk, exc
            )
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])
        finally:
            ensure_task_finalized(task)

        return task


class TrendParserError(Exception):
    pass
