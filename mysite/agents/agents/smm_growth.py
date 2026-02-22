"""
SMMGrowthAgent — еженедельный контент-план для VK, Instagram, Telegram.
Сохраняет 21 запись ContentPlan (7 дней × 3 платформы).
Запускается по понедельникам в 08:00 через run_weekly_agents.
"""
import datetime
import json
import logging

from django.conf import settings
from django.utils import timezone
from openai import OpenAI

from agents.models import AgentReport, AgentTask, ContentPlan
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)


class SMMGrowthAgent:

    def gather_data(self) -> dict:
        """
        Собирает:
        - последний отчёт OfferPackagesAgent (гипотезы офферов)
        - популярные услуги
        - последние отзывы
        - активные акции
        - текущий сезон/неделя
        """
        from services_app.models import Promotion, Review, Service

        today = datetime.date.today()
        week_num = today.isocalendar()[1]
        month = today.month
        season = (
            "зима" if month in (12, 1, 2) else
            "весна" if month in (3, 4, 5) else
            "лето" if month in (6, 7, 8) else
            "осень"
        )
        # Начало текущей недели (понедельник)
        week_start = today - datetime.timedelta(days=today.weekday())

        # --- Последний отчёт OfferPackagesAgent ---
        offer_hypotheses = []
        try:
            last_offer_report = (
                AgentReport.objects
                .filter(task__agent_type=AgentTask.OFFER_PACKAGES, task__status=AgentTask.DONE)
                .select_related("task")
                .order_by("-created_at")
                .first()
            )
            if last_offer_report and isinstance(last_offer_report.recommendations, list):
                offer_hypotheses = last_offer_report.recommendations[:3]
        except Exception as exc:
            logger.warning("SMMGrowthAgent: не удалось получить отчёт OfferPackages: %s", exc)

        # --- Популярные услуги ---
        popular = list(
            Service.objects.filter(is_active=True, is_popular=True)
            .values("name", "price_from", "emoji", "short_description")[:5]
        )
        if not popular:
            popular = list(
                Service.objects.filter(is_active=True)
                .values("name", "price_from", "emoji", "short_description")[:5]
            )

        # --- Последние отзывы ---
        reviews = []
        for r in Review.objects.filter(is_active=True).order_by("-date")[:5]:
            reviews.append({
                "author": r.author_name,
                "text": r.text[:150],
                "rating": r.rating,
            })

        # --- Активные акции ---
        promos = []
        for p in Promotion.objects.filter(is_active=True).order_by("order")[:5]:
            promos.append({"title": p.title, "discount": p.discount_percent})

        return {
            "date": today,
            "week_start": str(week_start),
            "week_num": week_num,
            "season": season,
            "offer_hypotheses": offer_hypotheses,
            "popular_services": popular,
            "reviews": reviews,
            "active_promotions": promos,
        }

    def _build_prompt(self, data: dict) -> str:
        services_str = "\n".join(
            f"  - {s.get('emoji', '')} {s['name']} от {s.get('price_from', '?')} руб."
            for s in data["popular_services"]
        ) or "  нет данных"
        reviews_str = "\n".join(
            f"  - {r['author']} ({r['rating']}★): {r['text']}"
            for r in data["reviews"]
        ) or "  нет отзывов"
        promos_str = "\n".join(
            f"  - {p['title']} -{p['discount']}%"
            for p in data["active_promotions"]
        ) or "  нет акций"
        offers_str = "\n".join(
            f"  - {h.get('title', '')}: {h.get('cta', '')}"
            for h in data["offer_hypotheses"]
        ) or "  нет гипотез (используй общие темы)"

        return (
            f"Сегодня {data['date']}, неделя №{data['week_num']}, сезон: {data['season']}.\n\n"
            f"УСЛУГИ САЛОНА:\n{services_str}\n\n"
            f"ОТЗЫВЫ КЛИЕНТОВ:\n{reviews_str}\n\n"
            f"ТЕКУЩИЕ АКЦИИ:\n{promos_str}\n\n"
            f"МАРКЕТИНГОВЫЕ ГИПОТЕЗЫ:\n{offers_str}\n\n"
            "Создай контент-план на 7 дней для трёх платформ: vk, instagram, telegram.\n"
            "Сценарий каждого поста: боль → экспертиза → кейс → оффер → CTA.\n"
            "Типы: post или story.\n\n"
            "Правила:\n"
            "- day_of_week: 0=пн, 1=вт, 2=ср, 3=чт, 4=пт, 5=сб, 6=вс\n"
            "- platform: vk, instagram или telegram\n"
            "- post_type: post или story\n"
            "- Создай ровно 21 запись (7 дней × 3 платформы)\n"
            "- Разные темы для разных дней\n\n"
            "Отвечай СТРОГО JSON без markdown:\n"
            '{"posts": [{"day_of_week": 0, "platform": "vk", "post_type": "post", '
            '"theme": "...", "description": "...", "hashtags": "#салон #красота", '
            '"cta": "Записаться по ссылке в шапке профиля"}]}'
        )

    def _save_content_plan(self, posts: list, task: AgentTask, week_start: str) -> int:
        """Bulk-create ContentPlan rows. Возвращает количество созданных записей."""
        week_start_date = datetime.date.fromisoformat(week_start)
        objs = []
        for p in posts:
            try:
                platform = p.get("platform", "telegram")
                if platform not in ("vk", "instagram", "telegram"):
                    platform = "telegram"
                post_type = p.get("post_type", "post")
                if post_type not in ("post", "story", "reel"):
                    post_type = "post"
                objs.append(ContentPlan(
                    week_start=week_start_date,
                    platform=platform,
                    day_of_week=int(p.get("day_of_week", 0)) % 7,
                    post_type=post_type,
                    theme=str(p.get("theme", ""))[:300],
                    description=str(p.get("description", "")),
                    hashtags=str(p.get("hashtags", "")),
                    cta=str(p.get("cta", ""))[:200],
                    created_by_task=task,
                    is_published=False,
                ))
            except Exception as exc:
                logger.warning("SMMGrowthAgent: пропускаем некорректный пост: %s", exc)
        if objs:
            ContentPlan.objects.bulk_create(objs)
        return len(objs)

    def run(self) -> AgentTask:
        task = AgentTask.objects.create(
            agent_type=AgentTask.SMM_GROWTH,
            status=AgentTask.RUNNING,
            triggered_by="scheduler",
        )
        logger.info("SMMGrowthAgent: старт (task_id=%s)", task.pk)
        try:
            data = self.gather_data()
            task.input_context = {
                k: (str(v) if isinstance(v, datetime.date) else v)
                for k, v in data.items()
                if k != "date"
            }
            task.save(update_fields=["input_context"])

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты SMM-специалист салона красоты. "
                            "Отвечай ТОЛЬКО валидным JSON без markdown."
                        ),
                    },
                    {"role": "user", "content": self._build_prompt(data)},
                ],
                response_format={"type": "json_object"},
                max_tokens=3500,
            )
            raw = response.choices[0].message.content.strip()
            task.raw_response = raw
            parsed = json.loads(raw)
            posts = parsed.get("posts", [])

            saved_count = self._save_content_plan(posts, task, data["week_start"])

            AgentReport.objects.create(
                task=task,
                summary=(
                    f"Контент-план создан: {saved_count} постов "
                    f"на неделю с {data['week_start']}"
                ),
                recommendations=posts[:3],  # превью в отчёте
            )

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            preview = "\n".join(
                f"• {p.get('platform', '').upper()} | "
                f"День {p.get('day_of_week', '?')} | {p.get('theme', '')[:60]}"
                for p in posts[:5]
            )
            send_telegram(
                f"📱 <b>Контент-план SMM</b> (неделя с {data['week_start']})\n"
                f"Создано постов: {saved_count}\n\n"
                f"{preview}"
            )
            logger.info(
                "SMMGrowthAgent: завершён (task_id=%s, постов=%d)", task.pk, saved_count
            )

        except Exception as exc:
            logger.exception("SMMGrowthAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])

        return task
