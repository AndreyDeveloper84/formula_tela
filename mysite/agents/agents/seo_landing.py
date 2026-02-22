"""
SEOLandingAgent — аудит SEO-лендингов услуг.
Оценивает каждую страницу по шкале 1–5, выявляет отсутствующие блоки.
Запускается по понедельникам в 08:00 через run_weekly_agents.
"""
import json
import logging

from django.conf import settings
from django.utils import timezone
from openai import OpenAI

from agents.models import AgentReport, AgentTask
from agents.telegram import send_telegram

logger = logging.getLogger(__name__)

# Блоки, которые должны быть на каждой хорошей посадочной странице
REQUIRED_BLOCKS = {"faq", "price_table", "checklist", "cta"}


class SEOLandingAgent:

    def gather_data(self) -> dict:
        """
        Для каждой активной услуги:
        - slug, seo_h1, seo_description
        - блоки: количество, типы, отсутствующие из REQUIRED_BLOCKS
        - пустые страницы (0 блоков)
        """
        from services_app.models import Service

        pages = []
        for svc in Service.objects.filter(is_active=True).prefetch_related("blocks"):
            blocks = list(svc.blocks.filter(is_active=True).values("block_type"))
            block_types_present = {b["block_type"] for b in blocks}
            missing = sorted(REQUIRED_BLOCKS - block_types_present)
            pages.append({
                "slug": svc.slug or str(svc.pk),
                "name": svc.name,
                "has_seo_h1": bool((svc.seo_h1 or "").strip()),
                "seo_description_len": len(svc.seo_description or ""),
                "block_count": len(blocks),
                "block_types": sorted(block_types_present),
                "missing_required_blocks": missing,
                "is_empty": len(blocks) == 0,
            })

        empty_pages = [p["slug"] for p in pages if p["is_empty"]]
        return {
            "total_services": len(pages),
            "empty_pages": empty_pages,
            "pages": pages,
        }

    def _build_prompt(self, data: dict) -> str:
        pages_summary = []
        for p in data["pages"][:30]:  # лимит токенов
            pages_summary.append(
                f"  slug={p['slug']} | блоков={p['block_count']} "
                f"| отсутствуют={p['missing_required_blocks']} "
                f"| h1={'✓' if p['has_seo_h1'] else '✗'} "
                f"| desc_len={p['seo_description_len']}"
            )
        pages_str = "\n".join(pages_summary)

        return (
            f"Аудит {data['total_services']} SEO-лендингов салона красоты.\n"
            f"Пустые страницы (0 блоков): {data['empty_pages'] or 'нет'}\n\n"
            f"ДАННЫЕ ПО СТРАНИЦАМ:\n{pages_str}\n\n"
            "Требования к хорошей странице: H1, SEO-description, "
            "блоки faq + price_table + checklist + cta.\n\n"
            "Для каждой страницы:\n"
            "- slug: слаг страницы\n"
            "- score: оценка 1-5 (5 = отличная страница)\n"
            "- missing_blocks: список отсутствующих блоков\n"
            "- recommendations: список конкретных действий (2-3 пункта)\n\n"
            "Приоритизируй страницы с оценкой 1-2 (критичные).\n\n"
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
            }
            task.save(update_fields=["input_context"])

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
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
            send_telegram(
                f"🔍 <b>SEO-аудит лендингов</b>\n"
                f"Страниц: {data['total_services']} | Критичных: {critical}\n\n"
                f"{summary[:400]}\n\n"
                f"<b>Худшие страницы:</b>\n{worst_str}"
            )
            logger.info("SEOLandingAgent: завершён (task_id=%s, страниц=%d)", task.pk, len(pages_result))

        except Exception as exc:
            logger.exception("SEOLandingAgent: ошибка (task_id=%s) — %s", task.pk, exc)
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])

        return task
