"""
SEOLandingAgent — аудит SEO-лендингов услуг.
Оценивает каждую страницу по шкале 1–5, выявляет отсутствующие блоки.
Обогащает данными Яндекс.Вебмастера: клики, показы, CTR, средняя позиция.
Детектирует WoW-просадки кликов (≥20%) и шлёт отдельный алерт.
Запускается по понедельникам в 08:00 через run_weekly_agents.
"""
import json
import logging
from datetime import date, timedelta

from django.conf import settings
from django.utils import timezone

from agents.agents import get_openai_client
from agents.agents._lifecycle import ensure_task_finalized
from agents.integrations.yandex_webmaster import YandexWebmasterClient, YandexWebmasterError
from agents.models import AgentReport, AgentTask, SeoRankSnapshot
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)

# Блоки, которые должны быть на каждой хорошей посадочной странице
REQUIRED_BLOCKS = {"faq", "price_table", "checklist", "cta"}

# Порог WoW-просадки кликов для алерта
CLICK_DROP_THRESHOLD = -0.20


def _get_week_start(d: date) -> date:
    """Возвращает понедельник недели для даты d."""
    return d - timedelta(days=d.weekday())


class SEOLandingAgent:

    def _fetch_webmaster_data(self, week_start: date) -> dict:
        """
        Загружает данные страниц и запросов из Яндекс.Вебмастера за текущую неделю.
        Сохраняет SeoRankSnapshot. Возвращает:
        {
            "pages_map": {"/uslugi/slug/": {clicks, impressions, ctr, avg_position}},
            "top_queries": [{query, clicks, impressions, ctr, avg_position}],
            "drops": [{url, clicks_now, clicks_prev, pct_drop}],
        }
        Если Вебмастер недоступен — возвращает пустой dict (graceful degradation).
        """
        result = {"pages_map": {}, "top_queries": [], "drops": []}
        try:
            wm = YandexWebmasterClient.from_settings()
            date_from = week_start.isoformat()
            date_to = (week_start + timedelta(days=6)).isoformat()
            prev_week_start = week_start - timedelta(days=7)

            # --- Страницы ---
            pages_wm = wm.get_top_pages(date_from, date_to)
            for p in pages_wm:
                result["pages_map"][p["url"]] = p

            # Сохраняем снимки страниц в БД
            for p in pages_wm:
                SeoRankSnapshot.objects.update_or_create(
                    week_start=week_start,
                    page_url=p["url"],
                    query="",
                    defaults={
                        "clicks": p["clicks"],
                        "impressions": p["impressions"],
                        "ctr": p["ctr"],
                        "avg_position": p["avg_position"],
                        "source": "webmaster",
                    },
                )

            # --- WoW-сравнение ---
            prev_snapshots = {
                s.page_url: s
                for s in SeoRankSnapshot.objects.filter(
                    week_start=prev_week_start, query=""
                )
            }
            for p in pages_wm:
                prev = prev_snapshots.get(p["url"])
                if prev and prev.clicks > 0:
                    pct = (p["clicks"] - prev.clicks) / prev.clicks
                    if pct <= CLICK_DROP_THRESHOLD:
                        result["drops"].append({
                            "url": p["url"],
                            "clicks_now": p["clicks"],
                            "clicks_prev": prev.clicks,
                            "pct_drop": round(pct * 100, 1),
                        })

            # --- Топ запросов ---
            queries_wm = wm.get_top_queries(date_from, date_to, limit=50)
            result["top_queries"] = queries_wm

            # Сохраняем снимки запросов в БД
            for q in queries_wm:
                if not q.get("query"):
                    continue
                SeoRankSnapshot.objects.update_or_create(
                    week_start=week_start,
                    page_url="",
                    query=q["query"],
                    defaults={
                        "clicks": q["clicks"],
                        "impressions": q["impressions"],
                        "ctr": q["ctr"],
                        "avg_position": q["avg_position"],
                        "source": "webmaster",
                    },
                )

            logger.info(
                "SEOLandingAgent: Вебмастер — %d страниц, %d запросов, %d просадок",
                len(pages_wm), len(queries_wm), len(result["drops"]),
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
        """
        from services_app.models import Service

        week_start = _get_week_start(date.today())
        wm = self._fetch_webmaster_data(week_start)
        pages_map = wm.get("pages_map", {})

        pages = []
        for svc in Service.objects.filter(is_active=True).prefetch_related("blocks"):
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
            })

        empty_pages = [p["slug"] for p in pages if p["is_empty"]]
        return {
            "total_services": len(pages),
            "empty_pages": empty_pages,
            "pages": pages,
            "webmaster_available": bool(pages_map),
            "drops": wm.get("drops", []),
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
            pages_summary.append(
                f"  slug={p['slug']} | блоков={p['block_count']} "
                f"| отсутствуют={p['missing_required_blocks']} "
                f"| h1={'✓' if p['has_seo_h1'] else '✗'} "
                f"| desc_len={p['seo_description_len']}"
                f"{wm_part}"
            )
        pages_str = "\n".join(pages_summary)

        wm_note = ""
        if data.get("webmaster_available"):
            wm_note = (
                "\nДанные Яндекс.Вебмастера за текущую неделю включены. "
                "Учитывай CTR и позиции при оценке приоритетов."
            )

        return (
            f"Аудит {data['total_services']} SEO-лендингов салона красоты.\n"
            f"Пустые страницы (0 блоков): {data['empty_pages'] or 'нет'}\n"
            f"{wm_note}\n\n"
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
            "и низким CTR повышай приоритет.\n\n"
            "Отвечай СТРОГО JSON без markdown:\n"
            '{"pages": [{"slug": "...", "score": 3, '
            '"missing_blocks": ["faq"], '
            '"recommendations": ["Добавить FAQ-блок с 5+ вопросами"]}], '
            '"critical_count": 2, "summary": "Общий вывод по аудиту"}'
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
                "drops_count": len(data.get("drops", [])),
            }
            task.save(update_fields=["input_context"])

            client = get_openai_client()
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты SEO-аудитор сайта салона красоты. "
                            "Отвечай ТОЛЬКО валидным JSON без markdown."
                        ),
                    },
                    {"role": "user", "content": self._build_prompt(data)},
                ],
                response_format={"type": "json_object"},
                max_tokens=3000,
            )
            raw = response.choices[0].message.content.strip()
            task.raw_response = raw
            parsed = json.loads(raw)
            pages_result = parsed.get("pages", [])
            critical = parsed.get("critical_count", 0)
            summary = parsed.get("summary", "")

            AgentReport.objects.create(
                task=task,
                summary=summary,
                recommendations=pages_result,
            )

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

            # Отдельный алерт при WoW-просадках кликов
            drops = data.get("drops", [])
            if drops:
                drops_str = "\n".join(
                    f"• {d['url']} | {d['clicks_prev']} → {d['clicks_now']} кл. "
                    f"({d['pct_drop']:+.0f}%)"
                    for d in sorted(drops, key=lambda x: x["pct_drop"])[:5]
                )
                send_telegram(
                    f"⚠️ <b>SEO: просадка кликов (WoW)</b>\n"
                    f"Страниц с падением ≥20%: {len(drops)}\n\n"
                    f"{drops_str}\n\n"
                    f"<b>Что делать:</b>\n"
                    f"1. Проверь изменения на странице за неделю\n"
                    f"2. Обнови Title/Description под запросы\n"
                    f"3. Проверь индексацию в Вебмастере"
                )

            logger.info(
                "SEOLandingAgent: завершён (task_id=%s, страниц=%d, просадок=%d)",
                task.pk, len(pages_result), len(drops),
            )

        except Exception as exc:
            logger.exception("SEOLandingAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])
        finally:
            ensure_task_finalized(task)

        return task
