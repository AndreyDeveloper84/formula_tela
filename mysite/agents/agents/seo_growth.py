"""
SEOGrowthAgent — стратегический SEO и growth-анализ.

Объединяет данные Вебмастера, Метрики и внутренней аналитики для формирования
стратегических гипотез роста трафика и конверсии.

Запускается еженедельно (понедельник) в составе run_weekly_agents.
"""
import datetime
import json
import logging

from django.conf import settings
from django.utils import timezone

from agents.agents import get_openai_client
from agents.agents._lifecycle import ensure_task_finalized
from agents.agents._outcomes import create_outcomes
from agents.models import AgentReport, AgentTask
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)


class SEOGrowthAgent:

    def _gather_webmaster_data(self) -> dict:
        """Позиции, CTR, клики из Вебмастера за 7 дней."""
        try:
            from agents.integrations.yandex_webmaster import (
                YandexWebmasterClient, YandexWebmasterError,
            )
            wm = YandexWebmasterClient.from_settings()
            today = datetime.date.today()
            date_from = (today - datetime.timedelta(days=7)).isoformat()
            date_to = today.isoformat()

            pages = wm.get_top_pages(date_from, date_to, limit=30)
            queries = wm.get_query_stats(date_from, date_to, limit=50)

            return {
                "pages": pages[:20],
                "queries": queries[:30],
                "total_clicks": sum(p.get("clicks", 0) for p in pages),
                "total_impressions": sum(p.get("impressions", 0) for p in pages),
            }
        except Exception as exc:
            logger.warning("SEOGrowthAgent: Вебмастер — %s", exc)
            return {}

    def _gather_metrika_data(self) -> dict:
        """Общие метрики сайта из Метрики за 30 дней."""
        try:
            from agents.integrations.yandex_metrika import (
                YandexMetrikaClient, YandexMetrikaError,
            )
            metrika = YandexMetrikaClient.from_settings()
            today = datetime.date.today()
            date_from = (today - datetime.timedelta(days=30)).isoformat()
            date_to = today.isoformat()

            summary = metrika.get_summary(date_from, date_to)
            organic = metrika.get_organic_sessions(date_from, date_to)

            return {
                "summary": summary,
                "organic": organic,
            }
        except Exception as exc:
            logger.warning("SEOGrowthAgent: Метрика — %s", exc)
            return {}

    def _gather_conversion_data(self) -> dict:
        """Данные конверсии: заявки, обработанные, топ услуг."""
        from services_app.models import BookingRequest, Service

        today = datetime.date.today()
        month_ago = today - datetime.timedelta(days=30)

        qs = BookingRequest.objects.filter(created_at__date__gte=month_ago)
        total = qs.count()
        processed = qs.filter(is_processed=True).count()

        by_service: dict[str, int] = {}
        for name in qs.values_list("service_name", flat=True):
            by_service[name] = by_service.get(name, 0) + 1
        top_services = sorted(by_service.items(), key=lambda x: x[1], reverse=True)[:10]

        active_services = Service.objects.filter(is_active=True).count()

        return {
            "total_leads": total,
            "processed_leads": processed,
            "conversion_pct": round(processed / total * 100) if total else 0,
            "top_services": top_services,
            "active_services_count": active_services,
        }

    def _gather_seo_tasks_data(self) -> dict:
        """Статус SEO-задач и рекомендаций."""
        from agents.models import AgentRecommendationOutcome, SeoTask

        open_tasks = SeoTask.objects.filter(
            status__in=[SeoTask.STATUS_OPEN, SeoTask.STATUS_IN_PROGRESS],
        ).count()
        escalated = SeoTask.objects.filter(escalation_count__gte=1).count()

        month_ago = datetime.date.today() - datetime.timedelta(days=30)
        outcomes = AgentRecommendationOutcome.objects.filter(created_at__date__gte=month_ago)
        outcome_stats = {
            "total": outcomes.count(),
            "accepted": outcomes.filter(status="accepted").count(),
            "rejected": outcomes.filter(status="rejected").count(),
            "done": outcomes.filter(status="done").count(),
        }

        return {
            "open_seo_tasks": open_tasks,
            "escalated_tasks": escalated,
            "recommendation_stats": outcome_stats,
        }

    def gather_data(self) -> dict:
        today = datetime.date.today()
        return {
            "date": today,
            "period": f"{today - datetime.timedelta(days=30)} — {today}",
            "webmaster": self._gather_webmaster_data(),
            "metrika": self._gather_metrika_data(),
            "conversion": self._gather_conversion_data(),
            "seo_tasks": self._gather_seo_tasks_data(),
        }

    def _build_prompt(self, data: dict) -> str:
        # Webmaster
        wm = data.get("webmaster", {})
        if wm:
            pages_str = "\n".join(
                f"  {p.get('url', '?')}: кл={p.get('clicks', 0)} "
                f"пок={p.get('impressions', 0)} CTR={p.get('ctr', 0):.1%} "
                f"поз={p.get('avg_position', 0):.1f}"
                for p in wm.get("pages", [])[:15]
            ) or "  нет данных"
            queries_str = "\n".join(
                f"  «{q.get('query', '?')}»: кл={q.get('clicks', 0)} "
                f"пок={q.get('impressions', 0)} поз={q.get('avg_position', 0):.1f}"
                for q in wm.get("queries", [])[:20]
            ) or "  нет данных"
            wm_section = (
                f"ВЕБМАСТЕР (7 дней):\n"
                f"Всего кликов: {wm.get('total_clicks', 0)}, "
                f"показов: {wm.get('total_impressions', 0)}\n"
                f"Топ страниц:\n{pages_str}\n"
                f"Топ запросов:\n{queries_str}"
            )
        else:
            wm_section = "ВЕБМАСТЕР: данные недоступны"

        # Metrika
        mk = data.get("metrika", {})
        summary = mk.get("summary", {})
        organic = mk.get("organic", {})
        if summary:
            mk_section = (
                f"МЕТРИКА (30 дней):\n"
                f"- Сессий: {summary.get('sessions', 0)}\n"
                f"- Отказы: {summary.get('bounce_rate', 0)}%\n"
                f"- Глубина: {summary.get('page_depth', 0)}\n"
                f"- Органика: {organic.get('sessions', 0)} сессий, "
                f"bounce={organic.get('bounce_rate', 0)}%"
            )
        else:
            mk_section = "МЕТРИКА: данные недоступны"

        # Conversion
        conv = data.get("conversion", {})
        top_svc = "\n".join(
            f"  {name}: {cnt} заявок" for name, cnt in conv.get("top_services", [])
        ) or "  нет данных"
        conv_section = (
            f"КОНВЕРСИЯ (30 дней):\n"
            f"- Заявок: {conv.get('total_leads', 0)}\n"
            f"- Обработано: {conv.get('processed_leads', 0)} "
            f"({conv.get('conversion_pct', 0)}%)\n"
            f"- Активных услуг на сайте: {conv.get('active_services_count', 0)}\n"
            f"- Топ услуг по заявкам:\n{top_svc}"
        )

        # SEO tasks
        seo = data.get("seo_tasks", {})
        rec = seo.get("recommendation_stats", {})
        seo_section = (
            f"SEO-ЗАДАЧИ:\n"
            f"- Открытых: {seo.get('open_seo_tasks', 0)}\n"
            f"- С эскалацией: {seo.get('escalated_tasks', 0)}\n"
            f"- Рекомендаций за месяц: {rec.get('total', 0)} "
            f"(принято {rec.get('accepted', 0)}, отклонено {rec.get('rejected', 0)}, "
            f"выполнено {rec.get('done', 0)})"
        )

        return (
            f"SEO и growth-анализ салона красоты «Формула тела» (Пенза).\n"
            f"Период: {data['period']}\n\n"
            f"{wm_section}\n\n"
            f"{mk_section}\n\n"
            f"{conv_section}\n\n"
            f"{seo_section}\n\n"
            "ЗАДАНИЕ:\n"
            "1. Найди 3-5 точек роста трафика (запросы с высокими показами но низким CTR, "
            "страницы без трафика, незанятые ниши)\n"
            "2. Найди 2-3 узких места в конверсии\n"
            "3. Для каждой точки роста сформулируй гипотезу:\n"
            "   'если сделать X → метрика Y изменится на Z% → потому что W'\n"
            "4. Выдели quick wins (результат за 1-3 дня) и стратегические задачи\n"
            "5. Предложи KPI для отслеживания\n\n"
            "Отвечай СТРОГО JSON:\n"
            '{"analysis": {"traffic_trend": "рост|стагнация|падение", '
            '"main_problems": ["..."], "main_opportunities": ["..."]}, '
            '"hypotheses": [{"title": "...", "action": "что сделать", '
            '"metric": "какая метрика изменится", "expected_change": "+15%", '
            '"reasoning": "потому что...", "priority": "high|medium|low", '
            '"type": "quick_win|strategic", "kpi": "что отслеживать"}], '
            '"kpi_targets": [{"metric": "...", "current": "...", '
            '"target": "...", "timeframe": "1 месяц"}]}'
        )

    def run(self) -> AgentTask:
        task = AgentTask.objects.create(
            agent_type=AgentTask.SEO_GROWTH,
            status=AgentTask.RUNNING,
            triggered_by="scheduler",
        )
        logger.info("SEOGrowthAgent: старт (task_id=%s)", task.pk)
        try:
            data = self.gather_data()
            task.input_context = {
                "webmaster_available": bool(data.get("webmaster")),
                "metrika_available": bool(data.get("metrika", {}).get("summary")),
                "total_leads": data.get("conversion", {}).get("total_leads", 0),
            }
            task.save(update_fields=["input_context"])

            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты senior SEO-стратег и growth-аналитик салона красоты в Пензе. "
                            "Принимаешь решения на основе данных Вебмастера, Метрики и воронки. "
                            "Формулируешь гипотезы роста с конкретными метриками и сроками. "
                            "Отвечай ТОЛЬКО валидным JSON без markdown."
                        ),
                    },
                    {"role": "user", "content": self._build_prompt(data)},
                ],
                response_format={"type": "json_object"},
                max_tokens=2500,
            )
            raw = response.choices[0].message.content.strip()
            task.raw_response = raw
            parsed = json.loads(raw)

            analysis = parsed.get("analysis", {})
            hypotheses = parsed.get("hypotheses", [])
            kpi_targets = parsed.get("kpi_targets", [])

            summary = (
                f"Тренд: {analysis.get('traffic_trend', '?')}. "
                f"Гипотез: {len(hypotheses)}. "
                f"Quick wins: {sum(1 for h in hypotheses if h.get('type') == 'quick_win')}."
            )

            report = AgentReport.objects.create(
                task=task,
                summary=summary,
                recommendations=hypotheses,
            )

            create_outcomes(report, AgentTask.SEO_GROWTH, hypotheses)

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            # Telegram
            quick_wins = [h for h in hypotheses if h.get("type") == "quick_win"]
            strategic = [h for h in hypotheses if h.get("type") == "strategic"]

            qw_str = "\n".join(
                f"• {h.get('title', '?')} → {h.get('expected_change', '?')}"
                for h in quick_wins[:3]
            ) or "нет"
            st_str = "\n".join(
                f"• {h.get('title', '?')} [{h.get('priority', '?')}]"
                for h in strategic[:3]
            ) or "нет"
            problems = "\n".join(
                f"• {p}" for p in analysis.get("main_problems", [])[:3]
            ) or "не выявлено"

            send_telegram(
                f"📈 <b>SEO & Growth анализ</b> ({data['period']})\n"
                f"Тренд: {analysis.get('traffic_trend', '?')}\n\n"
                f"<b>Проблемы:</b>\n{problems}\n\n"
                f"<b>Quick wins:</b>\n{qw_str}\n\n"
                f"<b>Стратегические:</b>\n{st_str}"
            )

            logger.info(
                "SEOGrowthAgent: завершён (task_id=%s, гипотез=%d)",
                task.pk, len(hypotheses),
            )

        except Exception as exc:
            logger.exception("SEOGrowthAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])
            from agents.telegram import send_agent_error_alert
            send_agent_error_alert(task)
        finally:
            ensure_task_finalized(task)

        return task
