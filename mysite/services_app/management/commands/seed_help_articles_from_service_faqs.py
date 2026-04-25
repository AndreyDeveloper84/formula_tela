"""Заполнить HelpArticle из существующих ServiceBlock(block_type='faq').

Каждый FAQ-блок услуги парсится через `website.templatetags.faq_tags.faq_items`
(формат: `Вопрос?\\nОтвет\\n---\\nВопрос?\\nОтвет`). Каждая пара Q&A → один
`HelpArticle` с пометкой источника в `answer` (без миграции схемы).

Идемпотентность: `update_or_create(question=...)` — повторный запуск обновит
ответ если он изменился, не плодит дубликаты по тому же вопросу.

Фильтрация:
- Пары без `?` в вопросе пропускаются (некоторые блоки используются НЕ для
  Q&A — например для описания процесса процедуры).
- Слишком короткие вопросы (<5 символов) пропускаются.

Запуск:
    python manage.py seed_help_articles_from_service_faqs --dry-run
    python manage.py seed_help_articles_from_service_faqs
    python manage.py seed_help_articles_from_service_faqs --purge-imported
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from services_app.models import HelpArticle, ServiceBlock
from website.templatetags.faq_tags import faq_items


# Маркер импортированных HelpArticle — добавляется в конец answer.
# По нему `--purge-imported` удаляет только наш импорт, не трогая ручные статьи.
SOURCE_MARKER = "\n\n_[Импортировано из FAQ услуги: "
SOURCE_MARKER_END = "]_"

MIN_QUESTION_LEN = 5
MAX_QUESTION_LEN = 255  # лимит CharField в HelpArticle


def _is_likely_question(text: str) -> bool:
    """Эвристика: настоящий вопрос содержит '?' и достаточно длинный."""
    text = text.strip()
    if len(text) < MIN_QUESTION_LEN:
        return False
    if "?" not in text:
        return False
    return True


def _truncate_question(text: str) -> str:
    """Если вопрос длиннее лимита HelpArticle.question — обрезаем по последнему '?'."""
    text = text.strip()
    if len(text) <= MAX_QUESTION_LEN:
        return text
    # Найти последний '?' в пределах лимита
    cut = text[:MAX_QUESTION_LEN]
    last_q = cut.rfind("?")
    if last_q > MIN_QUESTION_LEN:
        return cut[: last_q + 1]
    return cut.rstrip() + "…"


def _strip_html(text: str) -> str:
    """Убрать HTML (faq_items добавляет <br> в ответы)."""
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _format_answer(answer: str, service_name: str) -> str:
    return _strip_html(answer) + f"{SOURCE_MARKER}{service_name}{SOURCE_MARKER_END}"


class Command(BaseCommand):
    help = "Заполнить HelpArticle из ServiceBlock(block_type='faq')"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Печатает что было бы создано/обновлено, БЕЗ записи в БД",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Ограничить число обрабатываемых FAQ-блоков (0 = все)",
        )
        parser.add_argument(
            "--purge-imported", action="store_true",
            help="Удалить ВСЕ ранее импортированные HelpArticle (по SOURCE_MARKER)",
        )

    def handle(self, *args, **opts):
        if opts["purge_imported"]:
            self._purge_imported(dry_run=opts["dry_run"])
            return

        blocks = ServiceBlock.objects.filter(block_type="faq").select_related("service")
        if opts["limit"]:
            blocks = blocks[: opts["limit"]]

        stats = {"blocks_seen": 0, "qa_total": 0, "qa_skipped_no_q": 0,
                 "qa_skipped_short": 0, "created": 0, "updated": 0, "unchanged": 0}

        for block in blocks:
            stats["blocks_seen"] += 1
            service = block.service
            if not service:
                continue
            items = faq_items(block.content or "")
            stats["qa_total"] += len(items)

            for item in items:
                question = item.get("question", "").strip()
                answer = item.get("answer", "").strip()

                if not _is_likely_question(question):
                    stats["qa_skipped_no_q"] += 1
                    continue
                if len(question) < MIN_QUESTION_LEN:
                    stats["qa_skipped_short"] += 1
                    continue

                question = _truncate_question(question)
                full_answer = _format_answer(answer, service.name)

                if opts["dry_run"]:
                    self.stdout.write(f"[DRY] {service.name} → {question[:60]}…")
                    continue

                with transaction.atomic():
                    obj, created = HelpArticle.objects.update_or_create(
                        question=question,
                        defaults={"answer": full_answer, "is_active": True},
                    )
                    if created:
                        stats["created"] += 1
                    elif obj.answer != full_answer:
                        stats["updated"] += 1
                    else:
                        stats["unchanged"] += 1

        prefix = "[DRY] " if opts["dry_run"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Обработано блоков: {stats['blocks_seen']}, "
            f"Q&A пар: {stats['qa_total']} "
            f"(пропущено {stats['qa_skipped_no_q']} без '?', "
            f"{stats['qa_skipped_short']} коротких). "
            f"Создано: {stats['created']}, Обновлено: {stats['updated']}, "
            f"Без изменений: {stats['unchanged']}"
        ))

    def _purge_imported(self, dry_run: bool):
        qs = HelpArticle.objects.filter(answer__contains=SOURCE_MARKER.strip())
        n = qs.count()
        if dry_run:
            self.stdout.write(f"[DRY] Удалю {n} импортированных HelpArticle")
            for h in qs[:5]:
                self.stdout.write(f"  - {h.question[:60]}…")
            return
        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Удалено {deleted} импортированных HelpArticle"))
