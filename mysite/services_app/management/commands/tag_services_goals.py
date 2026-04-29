"""LLM-tagging Service.goals для consultative AI Concierge (Phase 2.4 T01).

Читает Service.name + description, запрашивает у gpt-4o-mini теги из
SERVICE_GOAL_CHOICES. Idempotent: skip услуг где goals уже заполнены,
если не передан --force.

Запуск:
  python manage.py tag_services_goals               # untagged only
  python manage.py tag_services_goals --force       # перетегировать всё
  python manage.py tag_services_goals --limit 10    # лимит за прогон
  python manage.py tag_services_goals --dry-run     # показать без save
  python manage.py tag_services_goals --service-id 42  # одна услуга

После прогона менеджер должен пройти по админке (`/admin/services_app/service/`,
filter «Цель / результат») и проверить теги. LLM может ошибаться (например
помечать «спортивный массаж» как relax — нужно убирать).
"""
from __future__ import annotations

import json
import logging

from django.core.management.base import BaseCommand, CommandError

from services_app.models import SERVICE_GOAL_CHOICES, SERVICE_GOAL_VALUES, Service

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
Ты — эксперт по массажу и SPA. Получаешь название и описание услуги,
возвращаешь список тегов из фиксированного словаря, которые описывают
ЦЕЛИ или РЕЗУЛЬТАТЫ услуги (что клиент получит).

Доступные теги (slug → русское описание):
{goals_dict}

Правила:
1. Возвращай ТОЛЬКО slug'и из этого словаря, ничего больше.
2. От 1 до 4 тегов на услугу — самые релевантные.
3. Если услуга подходит для нескольких целей — указывай 2-3.
4. Не выдумывай теги — только из словаря.
5. Если описание пустое или непонятно — верни пустой список [].

Отвечай строго в JSON формате:
{{"goals": ["tag1", "tag2"]}}
"""


def _build_system_prompt() -> str:
    goals_lines = "\n".join(f"- {slug}: {label}" for slug, label in SERVICE_GOAL_CHOICES)
    return SYSTEM_PROMPT.format(goals_dict=goals_lines)


def _classify_service(client, service: Service) -> list[str]:
    """Возвращает list[str] — slug'и goals из ответа LLM. Strict-валидация."""
    user_msg = (
        f"Название: {service.name}\n"
        f"Описание: {(service.description or '').strip()[:1500]}\n"
        f"Категория: {service.category.name if service.category else '—'}"
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=200,
    )
    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Service %s: invalid JSON: %r", service.id, raw[:200])
        return []

    goals = data.get("goals") or []
    if not isinstance(goals, list):
        return []
    # Filter out invented tags + dedupe + preserve order
    valid = []
    seen = set()
    for g in goals:
        if isinstance(g, str) and g in SERVICE_GOAL_VALUES and g not in seen:
            valid.append(g)
            seen.add(g)
    return valid


class Command(BaseCommand):
    help = "Auto-tag Service.goals через LLM (gpt-4o-mini)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force", action="store_true",
            help="Перетегировать даже услуги где goals уже заполнены.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Не сохранять — показать что было бы записано.",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Максимум услуг за прогон (для тестов).",
        )
        parser.add_argument(
            "--service-id", type=int, default=None,
            help="Тегировать только указанную услугу по id.",
        )

    def handle(self, *args, **opts):
        from agents.agents import get_openai_client

        client = get_openai_client()

        qs = Service.objects.filter(is_active=True).select_related("category")
        if opts["service_id"]:
            qs = qs.filter(id=opts["service_id"])
        elif not opts["force"]:
            # Только untagged (goals=[])
            qs = qs.filter(goals=[])

        if opts["limit"]:
            qs = qs[:opts["limit"]]

        services = list(qs)
        total = len(services)
        if total == 0:
            self.stdout.write(self.style.WARNING("Нет услуг для тегирования."))
            return

        self.stdout.write(f"Тегирую {total} услуг…")
        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING("DRY-RUN: changes не сохраняются"))

        tagged = 0
        empty = 0
        errors = 0
        for idx, service in enumerate(services, 1):
            try:
                goals = _classify_service(client, service)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(f"[{idx}/{total}] {service.name!r}: ERROR {exc}")
                errors += 1
                continue

            if not goals:
                empty += 1
                self.stdout.write(f"[{idx}/{total}] {service.name!r}: (нет тегов)")
                continue

            self.stdout.write(
                f"[{idx}/{total}] {service.name!r} → {goals}"
            )
            if not opts["dry_run"]:
                service.goals = goals
                service.save(update_fields=["goals", "updated_at"])
            tagged += 1

        self.stdout.write(self.style.SUCCESS(
            f"Готово: tagged={tagged} empty={empty} errors={errors} total={total}"
        ))
        if not opts["dry_run"] and tagged:
            self.stdout.write(
                "Проверь результат в админке: /admin/services_app/service/?goal=<slug>"
            )
