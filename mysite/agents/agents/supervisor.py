"""
Supervisor Agent — LLM-роутер: смотрит на контекст (день, последние запуски)
и решает, каких агентов запустить сегодня.
"""
import datetime
import json
import logging

from agents.agents._openai_cache import cached_chat_completion
from agents.models import AgentTask

logger = logging.getLogger(__name__)


class SupervisorAgent:
    def _get_context(self) -> dict:
        today = datetime.date.today()

        last_analytics = (
            AgentTask.objects.filter(agent_type=AgentTask.ANALYTICS, status=AgentTask.DONE)
            .order_by("-created_at")
            .first()
        )
        last_offers = (
            AgentTask.objects.filter(agent_type=AgentTask.OFFERS, status=AgentTask.DONE)
            .order_by("-created_at")
            .first()
        )

        return {
            "today": str(today),
            "weekday_ru": ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"][today.weekday()],
            "last_analytics_date": str(last_analytics.created_at.date()) if last_analytics else "никогда",
            "last_offers_date": str(last_offers.created_at.date()) if last_offers else "никогда",
            "days_since_analytics": (today - last_analytics.created_at.date()).days if last_analytics else 999,
            "days_since_offers": (today - last_offers.created_at.date()).days if last_offers else 999,
        }

    def decide(self) -> list[str]:
        """Возвращает список агентов для запуска: ['analytics'], ['offers'] или ['analytics', 'offers']."""
        ctx = self._get_context()

        prompt = (
            f"Контекст салона красоты на {ctx['today']} ({ctx['weekday_ru']}):\n"
            f"- Последний запуск аналитики: {ctx['last_analytics_date']} "
            f"({ctx['days_since_analytics']} дней назад)\n"
            f"- Последний запуск акций: {ctx['last_offers_date']} "
            f"({ctx['days_since_offers']} дней назад)\n\n"
            "Правила:\n"
            "- analytics: запускать если прошло >=1 дня с последнего запуска\n"
            "- offers: запускать в понедельник/четверг или если прошло >=3 дней\n"
            "- в понедельник запускать оба\n\n"
            'Ответь ТОЛЬКО JSON без пояснений: {"agents": ["analytics"]} '
            "или {\"agents\": [\"analytics\", \"offers\"]} и т.д."
        )

        try:
            raw = cached_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "Ты диспетчер AI-агентов. Отвечай строго JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                max_tokens=80,
            )
            data = json.loads(raw)
            agents = data.get("agents", [])
            # Валидация: только разрешённые значения
            valid = {AgentTask.ANALYTICS, AgentTask.OFFERS}
            result = [a for a in agents if a in valid]
            logger.info("SupervisorAgent решение: %s (контекст: %s)", result, ctx)
            return result or [AgentTask.ANALYTICS]
        except Exception as exc:
            logger.warning("SupervisorAgent: ошибка при принятии решения (%s), fallback → analytics", exc)
            from agents.telegram import send_telegram
            send_telegram(
                f"⚠️ SupervisorAgent: ошибка decide(), fallback → analytics\n"
                f"Ошибка: {str(exc)[:200]}"
            )
            return [AgentTask.ANALYTICS]

    def run(self):
        from agents.agents.analytics import AnalyticsAgent
        from agents.agents.offers import OfferAgent

        agents_to_run = self.decide()
        logger.info("SupervisorAgent: запускаем %s", agents_to_run)

        if AgentTask.ANALYTICS in agents_to_run:
            AnalyticsAgent().run()
        if AgentTask.OFFERS in agents_to_run:
            OfferAgent().run()

    def weekly_run(self):
        """
        Еженедельная синтез-задача (каждый понедельник в 08:00).
        Собирает последние отчёты всех агентов + feedback по рекомендациям →
        GPT синтезирует приоритизированный бэклог задач на неделю →
        сохраняет в WeeklyBacklog + отправляет в Telegram.
        """
        from agents.models import AgentRecommendationOutcome, AgentReport, WeeklyBacklog
        from agents.telegram import send_telegram

        agent_labels = {
            AgentTask.ANALYTICS:        "Аналитика (7 дней)",
            AgentTask.OFFERS:           "Акции (простые)",
            AgentTask.OFFER_PACKAGES:   "Пакеты и офферы",
            AgentTask.SMM_GROWTH:       "SMM-контент",
            AgentTask.SEO_LANDING:      "SEO-лендинги",
            AgentTask.ANALYTICS_BUDGET: "Бюджет и воронка",
            AgentTask.TREND_SCOUT:      "Разведка трендов",
            AgentTask.SEO_GROWTH:       "SEO & Growth стратегия",
        }

        # Собираем последние DONE-отчёты по каждому типу
        sections = []
        for atype, label in agent_labels.items():
            report = (
                AgentReport.objects
                .filter(task__agent_type=atype, task__status=AgentTask.DONE)
                .order_by("-created_at")
                .first()
            )
            if report:
                recs = report.recommendations
                recs_preview = ""
                if isinstance(recs, list) and recs:
                    recs_preview = "; ".join(
                        str(r.get("description", r) if isinstance(r, dict) else r)
                        for r in recs[:3]
                    )
                sections.append(
                    f"АГЕНТ: {label}\n"
                    f"Резюме: {report.summary[:300]}\n"
                    f"Рекомендации: {recs_preview or 'нет'}"
                )
            else:
                sections.append(f"АГЕНТ: {label}\nДанных нет")

        # Статистика feedback по рекомендациям за последние 7 дней
        import datetime as _dt
        week_ago = _dt.date.today() - _dt.timedelta(days=7)
        feedback_stats = {
            "new": AgentRecommendationOutcome.objects.filter(
                created_at__date__gte=week_ago, status=AgentRecommendationOutcome.STATUS_NEW
            ).count(),
            "accepted": AgentRecommendationOutcome.objects.filter(
                decided_at__date__gte=week_ago, status=AgentRecommendationOutcome.STATUS_ACCEPTED
            ).count(),
            "rejected": AgentRecommendationOutcome.objects.filter(
                decided_at__date__gte=week_ago, status=AgentRecommendationOutcome.STATUS_REJECTED
            ).count(),
            "done": AgentRecommendationOutcome.objects.filter(
                decided_at__date__gte=week_ago, status=AgentRecommendationOutcome.STATUS_DONE
            ).count(),
        }

        feedback_section = (
            f"FEEDBACK ЗА НЕДЕЛЮ:\n"
            f"- Новых рекомендаций: {feedback_stats['new']}\n"
            f"- Принято: {feedback_stats['accepted']}\n"
            f"- Отклонено: {feedback_stats['rejected']}\n"
            f"- Выполнено: {feedback_stats['done']}"
        )

        prompt = (
            "Еженедельный брифинг AI-агентов салона красоты:\n\n"
            + "\n\n".join(sections)
            + f"\n\n{feedback_section}\n\n"
            "Синтезируй единый приоритизированный бэклог задач на эту неделю. "
            "Учитывай feedback: если много отклонённых рекомендаций — "
            "скорректируй подход, если мало выполненных — сократи объём. "
            "Для каждого агента — топ 2-3 конкретных действия. "
            "Формат: Агент → Задача → Ожидаемый результат.\n"
            "Отвечай по-русски, лаконично."
        )

        try:
            text = cached_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты growth-директор салона красоты в Пензе. "
                            "Синтезируй данные всех агентов в единую стратегию. "
                            "Выделяй quick wins (результат за 1-3 дня) и стратегические задачи. "
                            "Приоритизируй по потенциалу ROI. "
                            "Отвечай чётко и по-русски."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1200,
            )

            # Сохраняем бэклог в БД
            today = _dt.date.today()
            week_start = today - _dt.timedelta(days=today.weekday())
            WeeklyBacklog.objects.update_or_create(
                week_start=week_start,
                defaults={"raw_text": text, "items": []},
            )

            week_str = today.strftime("%d.%m.%Y")
            fb_line = (
                f"\n\n📊 Feedback: принято {feedback_stats['accepted']}, "
                f"отклонено {feedback_stats['rejected']}, "
                f"выполнено {feedback_stats['done']}"
            )
            send_telegram(
                f"📋 <b>Еженедельный бэклог агентов</b> (неделя от {week_str})\n\n"
                f"{text[:3600]}{fb_line}"
            )
            logger.info("SupervisorAgent.weekly_run: бэклог сохранён и отправлен в Telegram")
        except Exception as exc:
            logger.exception("SupervisorAgent.weekly_run: ошибка — %s", exc)
