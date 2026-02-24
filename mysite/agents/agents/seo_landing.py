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

# Рекомендуемые длины мета-тегов
SEO_TITLE_MAX = 60
SEO_DESCRIPTION_MIN = 80
SEO_DESCRIPTION_MAX = 160


class SEOLandingAgent:

    # ------------------------------------------------------------------
    # Сбор данных
    # ------------------------------------------------------------------

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

    def gather_page_data(self, slug: str) -> dict | None:
        """
        Собирает полные SEO-данные для одной страницы по slug.
        Возвращает None, если услуга не найдена.
        """
        from services_app.models import Service

        try:
            svc = (
                Service.objects
                .filter(is_active=True, slug=slug)
                .prefetch_related("blocks", "media", "related_services")
                .first()
            )
        except Exception:
            svc = None

        if not svc:
            return None

        blocks = list(svc.blocks.filter(is_active=True).values("block_type", "title", "content"))
        block_types_present = {b["block_type"] for b in blocks}
        missing = sorted(REQUIRED_BLOCKS - block_types_present)

        media = list(svc.media.filter(is_active=True).values("alt_text", "title_text", "media_type"))
        media_without_alt = [m for m in media if not (m["alt_text"] or "").strip()]

        related = list(
            svc.related_services.filter(is_active=True)
            .values_list("slug", flat=True)
        )

        return {
            "slug": svc.slug or str(svc.pk),
            "name": svc.name,
            "has_seo_h1": bool((svc.seo_h1 or "").strip()),
            "seo_h1": svc.seo_h1 or "",
            "seo_title": svc.seo_title or "",
            "seo_title_len": len(svc.seo_title or ""),
            "seo_description": svc.seo_description or "",
            "seo_description_len": len(svc.seo_description or ""),
            "has_subtitle": bool((svc.subtitle or "").strip()),
            "block_count": len(blocks),
            "block_types": sorted(block_types_present),
            "blocks_detail": blocks,
            "missing_required_blocks": missing,
            "is_empty": len(blocks) == 0,
            "media_count": len(media),
            "media_without_alt": len(media_without_alt),
            "related_services_count": len(related),
            "related_services_slugs": related,
            "has_image": bool(svc.image),
        }

    # ------------------------------------------------------------------
    # Проверки без LLM (быстрые, локальные)
    # ------------------------------------------------------------------

    def get_empty_pages(self) -> list[dict]:
        """Возвращает список страниц с 0 активных блоков."""
        data = self.gather_data()
        return [p for p in data["pages"] if p["is_empty"]]

    def get_critical_pages(self) -> list[dict]:
        """
        Страницы с критичными SEO-проблемами (без LLM):
        - нет H1, нет SEO-description, пустая страница,
        - отсутствуют 3+ обязательных блока.
        """
        data = self.gather_data()
        critical = []
        for p in data["pages"]:
            problems = []
            if p["is_empty"]:
                problems.append("пустая_страница")
            if not p["has_seo_h1"]:
                problems.append("нет_h1")
            if p["seo_description_len"] == 0:
                problems.append("нет_description")
            if len(p["missing_required_blocks"]) >= 3:
                problems.append(f"нет_блоков:{','.join(p['missing_required_blocks'])}")
            if problems:
                critical.append({**p, "problems": problems})
        return sorted(critical, key=lambda x: -len(x["problems"]))

    def check_meta_quality(self) -> dict:
        """
        Проверяет качество мета-тегов (seo_title, seo_description) всех
        активных услуг. Возвращает статистику и список проблемных страниц.
        """
        from services_app.models import Service

        issues = []
        total = 0
        ok_count = 0

        for svc in Service.objects.filter(is_active=True):
            total += 1
            slug = svc.slug or str(svc.pk)
            page_issues = []

            title = svc.seo_title or ""
            desc = svc.seo_description or ""

            # seo_title
            if not title.strip():
                page_issues.append("seo_title пуст")
            elif len(title) > SEO_TITLE_MAX:
                page_issues.append(f"seo_title слишком длинный ({len(title)}/{SEO_TITLE_MAX})")

            # seo_description
            if not desc.strip():
                page_issues.append("seo_description пуст")
            elif len(desc) < SEO_DESCRIPTION_MIN:
                page_issues.append(
                    f"seo_description слишком короткий ({len(desc)}/{SEO_DESCRIPTION_MIN})"
                )
            elif len(desc) > SEO_DESCRIPTION_MAX:
                page_issues.append(
                    f"seo_description слишком длинный ({len(desc)}/{SEO_DESCRIPTION_MAX})"
                )

            # H1
            if not (svc.seo_h1 or "").strip():
                page_issues.append("seo_h1 пуст")

            if page_issues:
                issues.append({"slug": slug, "name": svc.name, "issues": page_issues})
            else:
                ok_count += 1

        return {
            "total": total,
            "ok": ok_count,
            "with_issues": len(issues),
            "pages": sorted(issues, key=lambda x: -len(x["issues"])),
        }

    def check_media_seo(self) -> dict:
        """
        Проверяет alt-тексты изображений на всех активных услугах.
        Возвращает страницы с изображениями без alt_text.
        """
        from services_app.models import Service

        pages_with_issues = []
        total_media = 0
        missing_alt_total = 0

        for svc in Service.objects.filter(is_active=True).prefetch_related("media"):
            media_items = list(svc.media.filter(is_active=True))
            if not media_items:
                continue
            total_media += len(media_items)
            without_alt = [m for m in media_items if not (m.alt_text or "").strip()]
            missing_alt_total += len(without_alt)
            if without_alt:
                pages_with_issues.append({
                    "slug": svc.slug or str(svc.pk),
                    "name": svc.name,
                    "total_media": len(media_items),
                    "missing_alt": len(without_alt),
                })

        return {
            "total_media": total_media,
            "missing_alt_total": missing_alt_total,
            "pages_with_issues": sorted(
                pages_with_issues, key=lambda x: -x["missing_alt"]
            ),
        }

    def check_internal_linking(self) -> dict:
        """
        Проверяет перелинковку (related_services) между услугами.
        Возвращает страницы без перелинковки и статистику.
        """
        from services_app.models import Service

        no_links = []
        total = 0
        linked = 0

        for svc in Service.objects.filter(is_active=True).prefetch_related("related_services"):
            total += 1
            related_count = svc.related_services.filter(is_active=True).count()
            if related_count > 0:
                linked += 1
            else:
                no_links.append({
                    "slug": svc.slug or str(svc.pk),
                    "name": svc.name,
                })

        return {
            "total": total,
            "with_links": linked,
            "without_links": len(no_links),
            "pages_without_links": no_links,
        }

    def bulk_check_required_blocks(self) -> list[dict]:
        """
        Быстрая проверка обязательных блоков по всем активным страницам
        (без вызова LLM). Возвращает только страницы с отсутствующими блоками.
        """
        data = self.gather_data()
        return [
            {
                "slug": p["slug"],
                "name": p["name"],
                "missing": p["missing_required_blocks"],
                "present": p["block_types"],
                "block_count": p["block_count"],
            }
            for p in data["pages"]
            if p["missing_required_blocks"]
        ]

    # ------------------------------------------------------------------
    # Сравнение с предыдущим аудитом
    # ------------------------------------------------------------------

    def compare_with_previous(self) -> dict:
        """
        Сравнивает текущее состояние страниц с последним завершённым аудитом.
        Возвращает улучшения и ухудшения.
        """
        last_report = (
            AgentReport.objects
            .filter(task__agent_type=AgentTask.SEO_LANDING, task__status=AgentTask.DONE)
            .select_related("task")
            .order_by("-created_at")
            .first()
        )
        if not last_report:
            return {"status": "no_previous_audit", "message": "Нет предыдущих аудитов для сравнения."}

        prev_pages = last_report.recommendations or []
        if not isinstance(prev_pages, list):
            return {"status": "invalid_previous_data", "message": "Данные предыдущего аудита повреждены."}

        prev_by_slug = {p.get("slug"): p for p in prev_pages if isinstance(p, dict)}

        current_data = self.gather_data()
        improved = []
        degraded = []
        new_pages = []

        for page in current_data["pages"]:
            slug = page["slug"]
            prev = prev_by_slug.get(slug)
            if not prev:
                new_pages.append(slug)
                continue

            prev_missing = set(prev.get("missing_blocks", []))
            curr_missing = set(page["missing_required_blocks"])

            fixed = sorted(prev_missing - curr_missing)
            broken = sorted(curr_missing - prev_missing)

            if fixed:
                improved.append({"slug": slug, "fixed_blocks": fixed})
            if broken:
                degraded.append({"slug": slug, "lost_blocks": broken})

        return {
            "status": "ok",
            "previous_audit_date": str(last_report.created_at.date()),
            "improved": improved,
            "degraded": degraded,
            "new_pages": new_pages,
            "summary": (
                f"Улучшено: {len(improved)}, ухудшено: {len(degraded)}, "
                f"новых страниц: {len(new_pages)}"
            ),
        }

    # ------------------------------------------------------------------
    # Функции с использованием LLM
    # ------------------------------------------------------------------

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

    def _build_single_page_prompt(self, page_data: dict) -> str:
        blocks_str = "\n".join(
            f"  - [{b['block_type']}] {b.get('title', '')}"
            for b in page_data.get("blocks_detail", [])
        ) or "  блоков нет"

        return (
            f"Детальный SEO-аудит страницы услуги «{page_data['name']}» "
            f"(slug: {page_data['slug']}) салона красоты.\n\n"
            f"SEO-ДАННЫЕ:\n"
            f"- H1: {page_data['seo_h1'] or '(пусто)'}\n"
            f"- Title: {page_data['seo_title'] or '(пусто)'} "
            f"({page_data['seo_title_len']} симв.)\n"
            f"- Description: {page_data['seo_description'] or '(пусто)'} "
            f"({page_data['seo_description_len']} симв.)\n"
            f"- Подзаголовок: {'есть' if page_data['has_subtitle'] else 'нет'}\n"
            f"- Главное изображение: {'есть' if page_data['has_image'] else 'нет'}\n\n"
            f"БЛОКИ ({page_data['block_count']}):\n{blocks_str}\n"
            f"Отсутствуют обязательные: {page_data['missing_required_blocks'] or 'все на месте'}\n\n"
            f"МЕДИА:\n"
            f"- Всего: {page_data['media_count']}\n"
            f"- Без alt-текста: {page_data['media_without_alt']}\n\n"
            f"ПЕРЕЛИНКОВКА:\n"
            f"- Связанных услуг: {page_data['related_services_count']}\n\n"
            "Проведи полный SEO-аудит этой страницы:\n"
            "1. score: общая оценка 1-5\n"
            "2. missing_blocks: отсутствующие обязательные блоки\n"
            "3. meta_issues: проблемы с мета-тегами (title, description, h1)\n"
            "4. media_issues: проблемы с изображениями\n"
            "5. linking_issues: проблемы с перелинковкой\n"
            "6. recommendations: 3-5 конкретных действий по приоритету\n"
            "7. suggested_title: предложение для seo_title (до 60 символов)\n"
            "8. suggested_description: предложение для seo_description (до 160 символов)\n\n"
            "Отвечай СТРОГО JSON без markdown:\n"
            '{"slug": "...", "score": 3, "missing_blocks": [], '
            '"meta_issues": [], "media_issues": [], "linking_issues": [], '
            '"recommendations": [], "suggested_title": "...", '
            '"suggested_description": "..."}'
        )

    def _build_seo_content_prompt(self, page_data: dict) -> str:
        return (
            f"Сгенерируй SEO-контент для страницы услуги «{page_data['name']}» "
            f"(slug: {page_data['slug']}) салона красоты «Формула Тела».\n\n"
            f"Текущее состояние:\n"
            f"- H1: {page_data['seo_h1'] or '(пусто)'}\n"
            f"- Title: {page_data['seo_title'] or '(пусто)'}\n"
            f"- Description: {page_data['seo_description'] or '(пусто)'}\n"
            f"- Блоков: {page_data['block_count']}\n"
            f"- Отсутствуют: {page_data['missing_required_blocks'] or 'нет'}\n\n"
            "Сгенерируй:\n"
            "1. seo_h1: H1-заголовок (включи ключевое слово услуги)\n"
            "2. seo_title: мета-заголовок до 60 символов\n"
            "3. seo_description: мета-описание 120-160 символов с CTA\n"
            "4. subtitle: подзаголовок под H1 (1-2 предложения)\n"
            "5. faq: 5 вопросов и ответов для FAQ-блока\n"
            "6. checklist_items: 5-7 пунктов для чеклиста (показания/преимущества)\n"
            "7. cta_text: текст для CTA-кнопки\n"
            "8. cta_subtext: подпись под кнопкой\n\n"
            "Отвечай СТРОГО JSON без markdown:\n"
            '{"seo_h1": "...", "seo_title": "...", "seo_description": "...", '
            '"subtitle": "...", '
            '"faq": [{"q": "...", "a": "..."}], '
            '"checklist_items": ["..."], '
            '"cta_text": "...", "cta_subtext": "..."}'
        )

    def audit_single_page(self, slug: str) -> AgentTask:
        """
        Детальный SEO-аудит одной страницы через LLM.
        Возвращает AgentTask с результатами.
        """
        task = AgentTask.objects.create(
            agent_type=AgentTask.SEO_LANDING,
            status=AgentTask.RUNNING,
            triggered_by="manual",
        )
        logger.info("SEOLandingAgent.audit_single_page: slug=%s (task_id=%s)", slug, task.pk)
        try:
            page_data = self.gather_page_data(slug)
            if not page_data:
                raise ValueError(f"Услуга с slug='{slug}' не найдена или неактивна.")

            task.input_context = {"slug": slug, "mode": "single_page_audit"}
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
                    {"role": "user", "content": self._build_single_page_prompt(page_data)},
                ],
                response_format={"type": "json_object"},
                max_tokens=1500,
            )
            raw = response.choices[0].message.content.strip()
            task.raw_response = raw
            parsed = json.loads(raw)

            AgentReport.objects.create(
                task=task,
                summary=f"Аудит /{slug}: оценка {parsed.get('score', '?')}/5",
                recommendations=[parsed],
            )

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            recs = parsed.get("recommendations", [])
            recs_str = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(recs[:3]))
            send_telegram(
                f"🔍 <b>SEO-аудит: /{slug}</b>\n"
                f"Оценка: {parsed.get('score', '?')}/5\n\n"
                f"<b>Рекомендации:</b>\n{recs_str}"
            )
            logger.info(
                "SEOLandingAgent.audit_single_page: завершён (task_id=%s, score=%s)",
                task.pk, parsed.get("score"),
            )

        except Exception as exc:
            logger.exception(
                "SEOLandingAgent.audit_single_page: ошибка (task_id=%s) — %s", task.pk, exc
            )
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])

        return task

    def generate_seo_content(self, slug: str) -> AgentTask:
        """
        Генерирует SEO-контент (H1, title, description, FAQ, чеклист, CTA)
        для конкретной страницы через LLM. Возвращает AgentTask.
        """
        task = AgentTask.objects.create(
            agent_type=AgentTask.SEO_LANDING,
            status=AgentTask.RUNNING,
            triggered_by="manual",
        )
        logger.info("SEOLandingAgent.generate_seo_content: slug=%s (task_id=%s)", slug, task.pk)
        try:
            page_data = self.gather_page_data(slug)
            if not page_data:
                raise ValueError(f"Услуга с slug='{slug}' не найдена или неактивна.")

            task.input_context = {"slug": slug, "mode": "generate_content"}
            task.save(update_fields=["input_context"])

            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты SEO-копирайтер для сайта салона красоты «Формула Тела». "
                            "Пиши по-русски, ёмко, с учётом поисковых запросов. "
                            "Отвечай ТОЛЬКО валидным JSON без markdown."
                        ),
                    },
                    {"role": "user", "content": self._build_seo_content_prompt(page_data)},
                ],
                response_format={"type": "json_object"},
                max_tokens=2000,
            )
            raw = response.choices[0].message.content.strip()
            task.raw_response = raw
            parsed = json.loads(raw)

            AgentReport.objects.create(
                task=task,
                summary=f"SEO-контент для /{slug}: H1, title, description, FAQ, чеклист, CTA",
                recommendations=[parsed],
            )

            task.status = AgentTask.DONE
            task.finished_at = timezone.now()
            task.save(update_fields=["raw_response", "status", "finished_at"])

            faq_count = len(parsed.get("faq", []))
            checklist_count = len(parsed.get("checklist_items", []))
            send_telegram(
                f"📝 <b>SEO-контент: /{slug}</b>\n\n"
                f"<b>Title:</b> {parsed.get('seo_title', '—')}\n"
                f"<b>H1:</b> {parsed.get('seo_h1', '—')}\n"
                f"<b>Description:</b> {parsed.get('seo_description', '—')[:100]}...\n\n"
                f"FAQ: {faq_count} вопросов | Чеклист: {checklist_count} пунктов"
            )
            logger.info(
                "SEOLandingAgent.generate_seo_content: завершён (task_id=%s)", task.pk
            )

        except Exception as exc:
            logger.exception(
                "SEOLandingAgent.generate_seo_content: ошибка (task_id=%s) — %s", task.pk, exc
            )
            task.status = AgentTask.ERROR
            task.error_message = str(exc)
            task.finished_at = timezone.now()
            task.save(update_fields=["status", "error_message", "finished_at"])

        return task

    # ------------------------------------------------------------------
    # Основной запуск (еженедельный аудит)
    # ------------------------------------------------------------------

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
