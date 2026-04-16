"""
AnalyticsBudgetAgent — воронка трафика + аналитика бюджета.
Источники: YClients, BookingRequest, Яндекс.Метрика, Яндекс.Директ, VK Реклама.
Запускается ежедневно в 09:00 через run_daily_agents.
"""
import datetime
import json
import logging

from django.conf import settings
from django.utils import timezone

from agents.agents import get_openai_client
from agents.agents._lifecycle import ensure_task_finalized
from agents.models import AgentReport, AgentTask, DailyMetric
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)


class AnalyticsBudgetAgent:

    def _gather_metrika(self, start: str, end: str) -> dict:
        """Получить данные из Яндекс.Метрики (graceful degradation при ошибке)."""
        try:
            from agents.integrations.yandex_metrika import YandexMetrikaClient
            client = YandexMetrikaClient.from_settings()
            return client.get_summary(date1=start, date2=end)
        except Exception as exc:
            logger.warning("AnalyticsBudgetAgent: Метрика недоступна: %s", exc)
            return {}

    def _gather_direct(self, date_from: str, date_to: str) -> dict:
        """Получить данные из Яндекс.Директ (graceful degradation при ошибке)."""
        try:
            from agents.integrations.yandex_direct import YandexDirectClient
            client = YandexDirectClient.from_settings()
            return client.get_campaign_stats(date_from=date_from, date_to=date_to)
        except Exception as exc:
            logger.warning("AnalyticsBudgetAgent: Директ недоступен: %s", exc)
            return {}

    def _gather_vk(self, date_from: str, date_to: str) -> dict:
        """Получить данные из VK Рекламы (graceful degradation при ошибке)."""
        try:
            from agents.integrations.vk_ads import VkAdsClient
            client = VkAdsClient.from_settings()
            return client.get_campaign_stats(date_from=date_from, date_to=date_to)
        except Exception as exc:
            logger.warning("AnalyticsBudgetAgent: VK Реклама недоступна: %s", exc)
            return {}

    def _gather_yclients(self, start: str, end: str) -> dict:
        """Получить визиты и выручку из YClients."""
        try:
            from services_app.yclients_api import get_yclients_api
            api = get_yclients_api()
            records = api.get_records(start_date=start, end_date=end)
            if not records:
                return {}
            from agents.agents._revenue import sum_records_revenue
            revenue = sum_records_revenue(records)
            statuses: dict[int, int] = {}
            for r in records:
                sid = int((r.get("status") or {}).get("id") or 0)
                statuses[sid] = statuses.get(sid, 0) + 1
            return {
                "yclients_visits": len(records),
                "yclients_revenue": round(revenue),
                "yclients_statuses": statuses,
            }
        except Exception as exc:
            logger.warning("AnalyticsBudgetAgent: YClients недоступен: %s", exc)
            return {}

    def gather_data(self) -> dict:
        from services_app.models import BookingRequest

        today = datetime.date.today()
        month_ago = today - datetime.timedelta(days=30)
        start_str, end_str = str(month_ago), str(today)

        # --- Локальная воронка заявок ---
        qs = BookingRequest.objects.filter(created_at__date__gte=month_ago)
        total_leads = qs.count()
        processed_leads = qs.filter(is_processed=True).count()

        # --- История DailyMetric (30д) ---
        metrics_history_count = DailyMetric.objects.filter(date__gte=month_ago).count()

        data: dict = {
            "period": f"{start_str} — {end_str}",
            "date": today,
            "leads_total": total_leads,
            "leads_processed": processed_leads,
            "leads_conversion_pct": (
                round(processed_leads / total_leads * 100) if total_leads else 0
            ),
            "metrics_history_days": metrics_history_count,
        }

        data.update(self._gather_metrika(start_str, end_str))
        data.update(self._gather_direct(start_str, end_str))
        data.update({"vk_" + k: v for k, v in self._gather_vk(start_str, end_str).items()})
        data.update(self._gather_yclients(start_str, end_str))

        return data

    def _build_prompt(self, data: dict) -> str:
        metrika_str = (
            f"  - Сессий: {data.get('sessions', 'н/д')}\n"
            f"  - Отказы: {data.get('bounce_rate', 'н/д')}%\n"
            f"  - Достижение целей: {data.get('goal_reaches', 'н/д')}\n"
            f"  - Глубина: {data.get('page_depth', 'н/д')} стр.\n"
            f"  - Топ-источники: {data.get('top_sources', 'н/д')}"
        )
        direct_str = (
            f"  - Кликов: {data.get('clicks', 'н/д')}\n"
            f"  - Расход: {data.get('cost', 'н/д')} руб.\n"
            f"  - CTR: {data.get('ctr', 'н/д')}%\n"
            f"  - Активных кампаний: {data.get('campaigns_count', 'н/д')}"
        )
        vk_str = (
            f"  - Показов: {data.get('vk_impressions', 'н/д')}\n"
            f"  - Кликов: {data.get('vk_clicks', 'н/д')}\n"
            f"  - Расход: {data.get('vk_cost', 'н/д')} руб.\n"
            f"  - CTR: {data.get('vk_ctr', 'н/д')}%\n"
            f"  - Активных кампаний: {data.get('vk_campaigns_count', 'н/д')}"
        )
        funnel_str = (
            f"  - Лидов с сайта: {data['leads_total']}\n"
            f"  - Обработано: {data['leads_processed']} ({data['leads_conversion_pct']}%)\n"
            f"  - Визитов YClients: {data.get('yclients_visits', 'н/д')}\n"
            f"  - Выручка: {data.get('yclients_revenue', 'н/д')} руб."
        )

        return (
            f"Данные салона красоты за {data['period']}:\n\n"
            f"ЯН.МЕТРИКА:\n{metrika_str}\n\n"
            f"ЯН.ДИРЕКТ:\n{direct_str}\n\n"
            f"VK РЕКЛАМА:\n{vk_str}\n\n"
            f"ВОРОНКА ЗАЯВОК:\n{funnel_str}\n\n"
            "Построй воронку: показы → клики → лид → запись → визит → чек → повтор.\n"
            "Найди узкие места (утечки) и предложи конкретные действия.\n\n"
            "Отвечай СТРОГО JSON без markdown:\n"
            '{"funnel": {"impressions": "...", "clicks": "...", "leads": "...", '
            '"bookings": "...", "visits": "...", "revenue": "..."}, '
            '"leaks": [{"stage": "...", "problem": "...", "impact": "высокий|средний|низкий"}], '
            '"actions": [{"priority": 1, "type": "budget|content|ux|ops", '
            '"description": "...", "expected_result": "..."}]}'
        )

    def run(self) -> AgentTask:
        task = AgentTask.objects.create(
            agent_type=AgentTask.ANALYTICS_BUDGET,
            status=AgentTask.RUNNING,
            triggered_by="scheduler",
        )
        logger.info("AnalyticsBudgetAgent: старт (task_id=%s)", task.pk)
        try:
            data = self.gather_data()
            task.input_context = {
                k: (str(v) if isinstance(v, datetime.date) else v)
                for k, v in data.items()
                if k != "date"
            }
            task.save(update_fields=["input_context"])

            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты performance-маркетолог с опытом в beauty-нише. "
                            "Отвечай ТОЛЬКО валидным JSON без markdown."
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
            actions = parsed.get("actions", [])
            leaks = parsed.get("leaks", [])

            report = AgentReport.objects.create(
                task=task,
                summary=f"Утечек в воронке: {len(leaks)}. Действий: {len(actions)}.",
                recommendations=actions,
            )

            # Feedback loop: трекинг рекомендаций
            from agents.agents._outcomes import create_outcomes
            create_outcomes(report, AgentTask.ANALYTICS_BUDGET, actions, title_key="description")

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            leaks_str = "\n".join(
                f"• <b>{lk.get('stage', '?')}</b> [{lk.get('impact', '?')}]: "
                f"{lk.get('problem', '')}"
                for lk in leaks[:3]
            )
            actions_str = "\n".join(
                f"{i + 1}. [{a.get('type', '').upper()}] {a.get('description', '')[:80]}"
                for i, a in enumerate(actions[:3])
            )
            send_telegram(
                f"💰 <b>Бюджет и воронка</b> ({data['period']})\n\n"
                f"<b>Утечки:</b>\n{leaks_str or 'не выявлено'}\n\n"
                f"<b>Топ действий:</b>\n{actions_str or 'нет'}"
            )
            logger.info(
                "AnalyticsBudgetAgent: завершён (task_id=%s, утечек=%d, действий=%d)",
                task.pk, len(leaks), len(actions),
            )

        except Exception as exc:
            logger.exception("AnalyticsBudgetAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])
            from agents.telegram import send_agent_error_alert
            send_agent_error_alert(task)
        finally:
            ensure_task_finalized(task)

        return task
