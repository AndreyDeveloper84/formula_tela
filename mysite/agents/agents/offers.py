"""
Offer Agent — анализирует загрузку мастеров и популярность услуг,
предлагает акции для увеличения загрузки через GPT.
"""
import datetime
import logging

from django.conf import settings
from django.utils import timezone

from agents.agents import get_openai_client
from agents.agents._lifecycle import ensure_task_finalized
from agents.models import AgentReport, AgentTask
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)


def _build_prompt(data: dict) -> str:
    low = "\n".join(
        f"  - {name}: {cnt} заявок за неделю"
        for name, cnt in data["low_demand_services"]
    ) or "  нет данных"
    active_promo = "\n".join(
        f"  - {p['title']} (скидка {p['discount']}%, до {p['ends_at']})"
        for p in data["active_promotions"]
    ) or "  нет активных акций"

    trends_section = ""
    if data.get("market_trends"):
        trends_lines = "\n".join(
            f"  - {t['topic']} (актуальность: {t.get('score', '?')}/10, "
            f"{t.get('detail', '')[:80]})"
            for t in data["market_trends"]
        )
        trends_section = f"- Актуальные тренды рынка:\n{trends_lines}\n"

    return (
        f"Данные салона красоты за период {data['period']}:\n"
        f"- Активных мастеров: {data['active_masters']}\n"
        f"- Услуги с низким спросом за 7 дней:\n{low}\n"
        f"- Текущие активные акции:\n{active_promo}\n"
        f"{trends_section}\n"
        "Предложи 2-3 конкретные акции (со скидкой или бонусом), которые помогут загрузить "
        "мастеров на ближайшую неделю. Учитывай рыночные тренды — предлагай акции на услуги, "
        "которые сейчас в тренде. Для каждой акции укажи: название, суть предложения, "
        "рекомендуемую скидку (%), на какую аудиторию направлена."
    )


class OfferAgent:
    def gather_data(self) -> dict:
        from services_app.models import BookingRequest, Master, Promotion, Service

        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        # Услуги с наименьшим числом заявок за 7 дней
        qs = BookingRequest.objects.filter(created_at__date__gte=week_ago)
        by_service: dict[str, int] = {}
        for req in qs.values_list("service_name", flat=True):
            by_service[req] = by_service.get(req, 0) + 1

        # Все активные услуги без заявок получают count=0
        all_services = list(Service.objects.filter(is_active=True).values_list(
            "name", flat=True
        ))
        for svc in all_services:
            if svc and svc not in by_service:
                by_service[svc] = 0

        low_demand = sorted(by_service.items(), key=lambda x: x[1])[:8]

        # Активные акции
        active_promotions = []
        for p in Promotion.objects.filter(is_active=True).order_by("-starts_at")[:5]:
            active_promotions.append({
                "title": p.title,
                "discount": p.discount_percent,
                "ends_at": str(p.ends_at) if p.ends_at else "бессрочно",
            })

        active_masters = Master.objects.filter(is_active=True).count()

        # Тренды рынка из TrendScoutAgent (если есть)
        from agents.models import TrendSnapshot
        market_trends = []
        snap = (
            TrendSnapshot.objects
            .exclude(trends=[])
            .order_by("-date")
            .first()
        )
        if snap and snap.trends:
            market_trends = snap.trends[:5]

        return {
            "period": f"{week_ago} — {today}",
            "date": today,
            "active_masters": active_masters,
            "low_demand_services": low_demand,
            "active_promotions": active_promotions,
            "market_trends": market_trends,
        }

    def run(self) -> AgentTask:
        task = AgentTask.objects.create(
            agent_type=AgentTask.OFFERS,
            status=AgentTask.RUNNING,
            triggered_by="scheduler",
        )
        logger.info("OfferAgent: старт (task_id=%s)", task.pk)
        try:
            data = self.gather_data()
            task.input_context = {k: v for k, v in data.items() if k != "date"}
            task.save(update_fields=["input_context"])

            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты маркетолог салона красоты. "
                            "Отвечай по-русски, давай конкретные предложения без вступлений."
                        ),
                    },
                    {"role": "user", "content": _build_prompt(data)},
                ],
                max_tokens=600,
            )
            text = response.choices[0].message.content.strip()
            task.raw_response = text

            AgentReport.objects.create(
                task=task,
                summary=text,
                recommendations=[],
            )

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            send_telegram(
                f"🎁 <b>Предложения по акциям</b> ({data['period']})\n\n{text[:900]}"
            )
            logger.info("OfferAgent: завершён (task_id=%s)", task.pk)

        except Exception as exc:
            logger.exception("OfferAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])
        finally:
            ensure_task_finalized(task)

        return task
