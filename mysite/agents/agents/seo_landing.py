"""
SEOLandingAgent — аудит SEO-лендингов услуг.
Оценивает каждую страницу по шкале 1–5, выявляет отсутствующие блоки.
Обогащает данными Яндекс.Вебмастера: клики, показы, CTR, средняя позиция.
Обогащает поведенческими метриками Яндекс.Метрики: bounce_rate, time_on_page.
Детектирует WoW-просадки кликов (≥20%) и шлёт отдельный алерт.
Запускается по понедельникам в 08:00 через run_weekly_agents.
"""
import json
import logging
import time
from datetime import date, timedelta

from django.utils import timezone

from agents.agents._lifecycle import ensure_task_finalized
from agents.agents._openai_cache import cached_chat_completion
from agents.integrations.yandex_webmaster import YandexWebmasterClient, YandexWebmasterError
from agents.models import AgentReport, AgentTask, SeoRankSnapshot
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)

# Блоки, которые должны быть на каждой хорошей посадочной странице
REQUIRED_BLOCKS = {"faq", "price_table", "checklist", "cta"}

# Порог WoW-просадки кликов для алерта
# WoW-просадки кликов определяются в analyze_rank_changes (tasks.py)
# — дедупликация и SeoTask escalation живут там.


def _get_week_start(d: date) -> date:
    """Возвращает понедельник недели для даты d."""
    return d - timedelta(days=d.weekday())


class SEOLandingAgent:

    def _fetch_metrika_behavior(self, page_urls: list[str], date_from: str, date_to: str) -> dict:
        """
        Загружает поведенческие метрики из Яндекс.Метрики для списка страниц.
        Возвращает {"/uslugi/slug/": {sessions, bounce_rate, time_on_page, goal_conversions}}.
        Graceful degradation: возвращает пустой dict при недоступности Метрики.
        """
        result = {}
        try:
            from agents.integrations.yandex_metrika import YandexMetrikaClient, YandexMetrikaError
            metrika = YandexMetrikaClient.from_settings()
        except Exception as exc:
            logger.warning("SEOLandingAgent: Метрика недоступна — %s", exc)
            return result

        for url in page_urls[:15]:  # лимит 15 страниц (rate limiting)
            try:
                behavior = metrika.get_page_behavior(url, date_from, date_to)
                if behavior.get("sessions", 0) > 0:
                    result[url] = behavior
                time.sleep(0.3)  # rate limiting
            except Exception as exc:
                logger.debug("SEOLandingAgent: Метрика для %s — %s", url, exc)
                continue

        logger.info("SEOLandingAgent: Метрика — %d страниц с данными", len(result))
        return result

    def _fetch_webmaster_data(self, week_start: date) -> dict:
        """
        Загружает данные страниц и запросов из Яндекс.Вебмастера за текущую неделю.
        Сохраняет SeoRankSnapshot. Возвращает:
        {
            "pages_map": {"/uslugi/slug/": {clicks, impressions, ctr, avg_position}},
            "top_queries": [{query, clicks, impressions, ctr, avg_position}],
        }
        WoW-просадки кликов определяются в analyze_rank_changes (tasks.py)
        — дедупликация и SeoTask escalation живут там.
        Если Вебмастер недоступен — возвращает пустой dict (graceful degradation).
        """
        result = {"pages_map": {}, "top_queries": []}

        # 1. Читаем свежие daily-снимки из БД (пишет collect_rank_snapshots 07:00).
        #    Окно: от начала недели до сегодня. Для одной и той же страницы/запроса
        #    берём самый свежий snapshot.
        from django.utils import timezone

        today = timezone.now().date()
        qs = SeoRankSnapshot.objects.filter(
            week_start__gte=week_start, week_start__lte=today,
            source="webmaster",
        ).order_by("-week_start")

        seen_pages, seen_queries = set(), set()
        for snap in qs:
            if snap.page_url and snap.page_url not in seen_pages:
                result["pages_map"][snap.page_url] = {
                    "url": snap.page_url,
                    "clicks": snap.clicks, "impressions": snap.impressions,
                    "ctr": snap.ctr, "avg_position": snap.avg_position,
                }
                seen_pages.add(snap.page_url)
            elif snap.query and snap.query not in seen_queries:
                result["top_queries"].append({
                    "query": snap.query,
                    "clicks": snap.clicks, "impressions": snap.impressions,
                    "ctr": snap.ctr, "avg_position": snap.avg_position,
                })
                seen_queries.add(snap.query)

        result["top_queries"].sort(key=lambda q: q["clicks"], reverse=True)
        result["top_queries"] = result["top_queries"][:50]

        if result["pages_map"] or result["top_queries"]:
            logger.info(
                "SEOLandingAgent: из SeoRankSnapshot — %d страниц, %d запросов",
                len(result["pages_map"]), len(result["top_queries"]),
            )
            return result

        # 2. Fallback на прямой вызов API — если daily-таск ещё не успел отработать
        #    (свежий деплой, Webmaster был недоступен и т.д.).
        logger.info("SEOLandingAgent: SeoRankSnapshot пуст, fallback на Webmaster API")
        try:
            wm = YandexWebmasterClient.from_settings()
            date_from = week_start.isoformat()
            date_to = (week_start + timedelta(days=6)).isoformat()

            pages_wm = wm.get_top_pages(date_from, date_to)
            for p in pages_wm:
                result["pages_map"][p["url"]] = p

            result["top_queries"] = wm.get_top_queries(date_from, date_to, limit=50)

            logger.info(
                "SEOLandingAgent: Вебмастер API — %d страниц, %d запросов",
                len(pages_wm), len(result["top_queries"]),
            )
        except YandexWebmasterError as exc:
            logger.warning("SEOLandingAgent: Вебмастер недоступен — %s", exc)
        except Exception as exc:
            logger.exception("SEOLandingAgent: ошибка при получении данных Вебмастера — %s", exc)

        return result

    def gather_data(self) -> dict:
        """
        Для каждой активной услуги:
        - slug, seo_h1, seo_description
        - блоки: количество, типы, отсутствующие из REQUIRED_BLOCKS
        - пустые страницы (0 блоков)
        - данные Вебмастера: клики, показы, CTR, позиция (если доступны)
        - поведенческие метрики Метрики: bounce_rate, time_on_page (для топ-15 по impressions)
        """
        from services_app.models import Service

        week_start = _get_week_start(date.today())
        wm = self._fetch_webmaster_data(week_start)
        pages_map = wm.get("pages_map", {})

        pages = []
        for svc in Service.objects.active().prefetch_related("blocks"):
            blocks = list(svc.blocks.filter(is_active=True).values("block_type"))
            block_types_present = {b["block_type"] for b in blocks}
            missing = sorted(REQUIRED_BLOCKS - block_types_present)

            slug = svc.slug or str(svc.pk)
            page_url = f"/uslugi/{slug}/"
            wm_data = pages_map.get(page_url, {})

            pages.append({
                "slug": slug,
                "name": svc.name,
                "has_seo_h1": bool((svc.seo_h1 or "").strip()),
                "seo_description_len": len(svc.seo_description or ""),
                "block_count": len(blocks),
                "block_types": sorted(block_types_present),
                "missing_required_blocks": missing,
                "is_empty": len(blocks) == 0,
                # Данные Вебмастера
                "wm_clicks": wm_data.get("clicks", 0),
                "wm_impressions": wm_data.get("impressions", 0),
                "wm_ctr": wm_data.get("ctr", 0.0),
                "wm_avg_position": wm_data.get("avg_position"),
                # Поведенческие метрики (заполняются ниже)
                "metrika_bounce_rate": 0.0,
                "metrika_time_on_page": 0.0,
                "metrika_sessions": 0,
            })

        # Поведенческие метрики Метрики для топ-15 страниц по impressions
        top_pages_by_impressions = sorted(
            [p for p in pages if p["wm_impressions"] > 0],
            key=lambda x: x["wm_impressions"],
            reverse=True,
        )[:15]
        if top_pages_by_impressions:
            date_from = week_start.isoformat()
            date_to = (week_start + timedelta(days=6)).isoformat()
            page_urls = [f"/uslugi/{p['slug']}/" for p in top_pages_by_impressions]
            behavior_map = self._fetch_metrika_behavior(page_urls, date_from, date_to)
            for p in pages:
                url = f"/uslugi/{p['slug']}/"
                bh = behavior_map.get(url, {})
                if bh:
                    p["metrika_bounce_rate"] = bh.get("bounce_rate", 0.0)
                    p["metrika_time_on_page"] = bh.get("time_on_page", 0.0)
                    p["metrika_sessions"] = bh.get("sessions", 0)

        empty_pages = [p["slug"] for p in pages if p["is_empty"]]
        metrika_available = any(p["metrika_sessions"] > 0 for p in pages)
        return {
            "total_services": len(pages),
            "empty_pages": empty_pages,
            "pages": pages,
            "webmaster_available": bool(pages_map),
            "metrika_available": metrika_available,
            "top_queries": wm.get("top_queries", [])[:10],
        }

    def _build_prompt(self, data: dict) -> str:
        pages_summary = []
        for p in data["pages"][:30]:  # лимит токенов
            wm_part = ""
            if data.get("webmaster_available"):
                pos = (
                    f"{p['wm_avg_position']:.1f}"
                    if p["wm_avg_position"] is not None
                    else "—"
                )
                wm_part = (
                    f" | кл={p['wm_clicks']} пок={p['wm_impressions']} "
                    f"CTR={p['wm_ctr']:.1%} поз={pos}"
                )
            metrika_part = ""
            if p.get("metrika_sessions", 0) > 0:
                metrika_part = (
                    f" | bounce={p['metrika_bounce_rate']:.0f}% "
                    f"time={p['metrika_time_on_page']:.0f}s "
                    f"visits={p['metrika_sessions']}"
                )
            pages_summary.append(
                f"  slug={p['slug']} | блоков={p['block_count']} "
                f"| отсутствуют={p['missing_required_blocks']} "
                f"| h1={'✓' if p['has_seo_h1'] else '✗'} "
                f"| desc_len={p['seo_description_len']}"
                f"{wm_part}{metrika_part}"
            )
        pages_str = "\n".join(pages_summary)

        wm_note = ""
        if data.get("webmaster_available"):
            wm_note = (
                "\nДанные Яндекс.Вебмастера за текущую неделю включены. "
                "Учитывай CTR и позиции при оценке приоритетов."
            )
        metrika_note = ""
        if data.get("metrika_available"):
            metrika_note = (
                "\nДанные Яндекс.Метрики включены (bounce, time, visits). "
                "Если bounce > 70% и time < 30s — проблема с контентом, score не выше 2."
            )

        return (
            f"Аудит {data['total_services']} SEO-лендингов салона красоты.\n"
            f"Пустые страницы (0 блоков): {data['empty_pages'] or 'нет'}\n"
            f"{wm_note}{metrika_note}\n\n"
            f"ДАННЫЕ ПО СТРАНИЦАМ:\n{pages_str}\n\n"
            "Требования к хорошей странице: H1, SEO-description, "
            "блоки faq + price_table + checklist + cta.\n\n"
            "Для каждой страницы:\n"
            "- slug: слаг страницы\n"
            "- score: оценка 1-5 (5 = отличная страница)\n"
            "- missing_blocks: список отсутствующих блоков\n"
            "- recommendations: список конкретных действий (2-3 пункта)\n\n"
            "Приоритизируй страницы с оценкой 1-2 (критичные).\n"
            "Если доступны данные Вебмастера — страницам с высокими показами "
            "и низким CTR повышай приоритет.\n"
            "Если bounce > 70% и time < 30s — рекомендуй переписать intro и добавить CTA.\n\n"
            "Для каждой страницы с score <= 3 сформулируй гипотезу роста:\n"
            "hypothesis: 'если сделать X → Y изменится → потому что Z'\n\n"
            "Отвечай СТРОГО JSON без markdown:\n"
            '{"pages": [{"slug": "...", "score": 3, '
            '"missing_blocks": ["faq"], '
            '"recommendations": ["Добавить FAQ-блок с 5+ вопросами"], '
            '"hypothesis": "если добавить FAQ → bounce снизится на 10-15% → '
            'потому что пользователь найдёт ответы на вопросы"}], '
            '"critical_count": 2, "summary": "Общий вывод по аудиту", '
            '"quick_wins": ["быстрые победы — что даст результат за 1-2 дня"]}'
        )

    def run(self) -> AgentTask:
        task = AgentTask.objects.create(
            agent_type=AgentTask.SEO_LANDING,
            status=AgentTask.RUNNING,
            triggered_by="scheduler",
        )
        logger.info("SEOLandingAgent: старт (task_id=%s)", task.pk)
        try:
            data = self.gather_data()
            task.input_context = {
                "total_services": data["total_services"],
                "empty_pages": data["empty_pages"],
                "webmaster_available": data["webmaster_available"],
                "metrika_available": data.get("metrika_available", False),
            }
            task.save(update_fields=["input_context"])

            raw = cached_chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты senior SEO-аудитор и growth-аналитик сайта салона красоты в Пензе. "
                            "Ты анализируешь не только техническое SEO, но и поведенческие факторы, "
                            "воронку конверсии и точки роста. "
                            "Для каждой проблемной страницы формулируй гипотезу: "
                            "'если сделать X → метрика Y изменится → потому что Z'. "
                            "Приоритизируй по потенциалу роста трафика и конверсии. "
                            "Отвечай ТОЛЬКО валидным JSON без markdown."
                        ),
                    },
                    {"role": "user", "content": self._build_prompt(data)},
                ],
                response_format={"type": "json_object"},
                max_tokens=3000,
            )
            task.raw_response = raw
            parsed = json.loads(raw)
            pages_result = parsed.get("pages", [])
            critical = parsed.get("critical_count", 0)
            summary = parsed.get("summary", "")

            report = AgentReport.objects.create(
                task=task,
                summary=summary,
                recommendations=pages_result,
            )

            # Feedback loop: трекинг рекомендаций для критичных страниц (score <= 3)
            from agents.agents._outcomes import create_outcomes
            critical_pages = [p for p in pages_result if p.get("score", 5) <= 3]
            create_outcomes(report, AgentTask.SEO_LANDING, critical_pages, title_key="slug")

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            # Топ-3 худших страницы для Telegram
            worst = sorted(pages_result, key=lambda x: x.get("score", 5))[:3]
            worst_str = "\n".join(
                f"• /{p.get('slug', '?')} — {p.get('score', '?')}/5: "
                + (p.get("recommendations", [""])[0] if p.get("recommendations") else "")
                for p in worst
            )

            wm_status = (
                "✅ данные Вебмастера подключены"
                if data.get("webmaster_available")
                else "⚠️ Вебмастер недоступен"
            )
            send_telegram(
                f"🔍 <b>SEO-аудит лендингов</b>\n"
                f"Страниц: {data['total_services']} | Критичных: {critical} | {wm_status}\n\n"
                f"{summary[:400]}\n\n"
                f"<b>Худшие страницы:</b>\n{worst_str}"
            )

            logger.info(
                "SEOLandingAgent: завершён (task_id=%s, страниц=%d)",
                task.pk, len(pages_result),
            )

        except Exception as exc:
            logger.exception("SEOLandingAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])
            from agents.telegram import send_agent_error_alert
            send_agent_error_alert(task)
        finally:
            ensure_task_finalized(task)

        return task
