"""
OfferPackagesAgent — еженедельные гипотезы офферов/пакетов по сегментам клиентов.
Запускается по понедельникам в 08:00 через run_weekly_agents.
"""
import datetime
import json
import logging

from django.conf import settings
from django.utils import timezone

from agents.agents import get_openai_client
from agents.agents._json_utils import to_jsonable
from agents.agents._lifecycle import ensure_task_finalized
from agents.models import AgentReport, AgentTask
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)


class OfferPackagesAgent:

    def gather_data(self) -> dict:
        """
        Собирает за 30 дней:
        - спрос на услуги (BookingRequest по service_name)
        - активные услуги, акции, бандлы
        - данные YClients (визиты, выручка, топ-услуги)
        """
        from services_app.models import BookingRequest, Bundle, Promotion, Service

        today = datetime.date.today()
        month_ago = today - datetime.timedelta(days=30)

        # --- Спрос на услуги (30д) ---
        qs = BookingRequest.objects.filter(created_at__date__gte=month_ago)
        by_service: dict[str, int] = {}
        for name in qs.values_list("service_name", flat=True):
            if name:
                by_service[name] = by_service.get(name, 0) + 1
        demand_sorted = sorted(by_service.items(), key=lambda x: -x[1])

        # --- Активные услуги ---
        services = list(
            Service.objects.filter(is_active=True)
            .values("name", "price_from", "emoji", "short_description")[:30]
        )

        # --- Активные акции ---
        promos = []
        for p in Promotion.objects.filter(is_active=True).order_by("order")[:10]:
            promos.append({
                "title": p.title,
                "discount": p.discount_percent,
                "promo_code": p.promo_code or "",
                "ends_at": str(p.ends_at) if hasattr(p, "ends_at") and p.ends_at else "бессрочно",
            })

        # --- Активные бандлы ---
        bundles = []
        for b in Bundle.objects.filter(is_active=True)[:10]:
            bundles.append({
                "name": b.name,
                "item_count": b.items.count(),
            })

        # --- YClients (30д) ---
        yc_data: dict = {}
        try:
            from services_app.yclients_api import get_yclients_api
            api = get_yclients_api()
            records = api.get_records(str(month_ago), str(today))
            if records:
                revenue = sum(float(r.get("sum") or 0) for r in records)
                svc_counts: dict[str, int] = {}
                for r in records:
                    for s in r.get("services", []):
                        n = s.get("title") or s.get("name") or "?"
                        svc_counts[n] = svc_counts.get(n, 0) + 1
                yc_data = {
                    "yclients_total": len(records),
                    "yclients_revenue_30d": round(revenue),
                    "yclients_top_services": sorted(svc_counts.items(), key=lambda x: -x[1])[:10],
                }
        except Exception as exc:
            logger.warning("OfferPackagesAgent: YClients недоступен: %s", exc)

        return {
            "period": f"{month_ago} — {today}",
            "date": today,
            "booking_demand": demand_sorted,
            "services": services,
            "active_promotions": promos,
            "active_bundles": bundles,
            **yc_data,
        }

    def _build_prompt(self, data: dict) -> str:
        demand_str = "\n".join(
            f"  - {n}: {c} заявок" for n, c in data["booking_demand"][:15]
        ) or "  нет данных"
        promo_str = "\n".join(
            f"  - {p['title']} ({p['discount']}%)" for p in data["active_promotions"]
        ) or "  нет активных акций"
        bundles_str = "\n".join(
            f"  - {b['name']} ({b['item_count']} позиций)" for b in data["active_bundles"]
        ) or "  нет пакетов"
        yc_str = ""
        if data.get("yclients_total"):
            yc_str = (
                f"\nYCLIENTS (30д):\n"
                f"  - Визитов: {data['yclients_total']}\n"
                f"  - Выручка: {data.get('yclients_revenue_30d', 0)} руб.\n"
            )

        return (
            f"Данные салона красоты за период {data['period']}:\n\n"
            f"СПРОС НА УСЛУГИ (заявки с сайта, 30 дней):\n{demand_str}\n\n"
            f"ТЕКУЩИЕ АКЦИИ:\n{promo_str}\n\n"
            f"ТЕКУЩИЕ КОМПЛЕКСЫ:\n{bundles_str}\n"
            f"{yc_str}\n"
            "Ты ведущий маркетолог салона красоты. Сгенерируй 3–5 гипотез офферов "
            "для увеличения записей и среднего чека.\n\n"
            "Для каждой гипотезы:\n"
            "- title: название оффера\n"
            "- segment: один из [new, returning, vip, problem_zones]\n"
            "- pain: боль клиента\n"
            "- solution: наше решение\n"
            "- proof: доказательство/соц.доказательство\n"
            "- cta: призыв к действию\n"
            "- social_text: 2-3 предложения для поста в соцсетях\n"
            "- landing_brief: что изменить на посадочной странице\n"
            "- predicted_cr_lift: прогнозируемый рост конверсии (например '+10-15%')\n\n"
            "Отвечай СТРОГО JSON без markdown:\n"
            '{"hypotheses": [{"title": "...", "segment": "...", "pain": "...", '
            '"solution": "...", "proof": "...", "cta": "...", '
            '"social_text": "...", "landing_brief": "...", "predicted_cr_lift": "..."}]}'
        )

    def run(self) -> AgentTask:
        task = AgentTask.objects.create(
            agent_type=AgentTask.OFFER_PACKAGES,
            status=AgentTask.RUNNING,
            triggered_by="scheduler",
        )
        logger.info("OfferPackagesAgent: старт (task_id=%s)", task.pk)
        try:
            data = self.gather_data()
            task.input_context = to_jsonable(
                {k: v for k, v in data.items() if k != "date"}
            )
            task.save(update_fields=["input_context"])

            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты ведущий growth-маркетолог салона красоты в Пензе. "
                            "Генерируй гипотезы офферов на основе реальных данных о спросе. "
                            "Для каждой гипотезы указывай predicted_cr_lift с обоснованием. "
                            "Отвечай ТОЛЬКО валидным JSON без markdown-блоков."
                        ),
                    },
                    {"role": "user", "content": self._build_prompt(data)},
                ],
                response_format={"type": "json_object"},
                max_tokens=2000,
            )
            raw = response.choices[0].message.content.strip()
            task.raw_response = raw
            parsed = json.loads(raw)
            hypotheses = parsed.get("hypotheses", [])

            report = AgentReport.objects.create(
                task=task,
                summary=f"Сгенерировано {len(hypotheses)} гипотез офферов за {data['period']}",
                recommendations=hypotheses,
            )

            # Feedback loop: трекинг рекомендаций
            from agents.agents._outcomes import create_outcomes
            create_outcomes(report, AgentTask.OFFER_PACKAGES, hypotheses)

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            preview = "\n".join(
                f"• <b>{h.get('title', '')}</b> [{h.get('segment', '')}] — {h.get('cta', '')}"
                for h in hypotheses[:3]
            )
            send_telegram(
                f"💡 <b>Гипотезы офферов</b> ({data['period']})\n"
                f"Сгенерировано: {len(hypotheses)} предложений\n\n"
                f"{preview}"
            )
            logger.info("OfferPackagesAgent: завершён (task_id=%s, гипотез=%d)", task.pk, len(hypotheses))

        except Exception as exc:
            logger.exception("OfferPackagesAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])
            from agents.telegram import send_agent_error_alert
            send_agent_error_alert(task)
        finally:
            ensure_task_finalized(task)

        return task
