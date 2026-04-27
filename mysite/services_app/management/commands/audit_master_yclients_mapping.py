"""Audit `Master.yclients_staff_id` — кто из активных мастеров готов к AI-booking.

Зачем: Phase 2.3 native YClients-booking требует чтобы у каждого Master в БД
было заполнено поле `yclients_staff_id`. Без него AI Concierge не сможет
сделать запись через YClients API.

Сравнивает:
- Активные Master в БД vs YClients staff (через get_staff API)
- Алертит:
  - Master.is_active=True но yclients_staff_id пустой
  - Master.yclients_staff_id указан но в YClients такого нет (некорректный ID)
  - YClients staff есть, но в нашей БД нет соответствующего Master

Запуск:
    python manage.py audit_master_yclients_mapping
    python manage.py audit_master_yclients_mapping --skip-yclients-call  # только локальный аудит

Безопасно — read-only, ничего не меняет.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from services_app.models import Master


class Command(BaseCommand):
    help = "Аудит Master.yclients_staff_id для AI native booking (Phase 2.3)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-yclients-call",
            action="store_true",
            help="Не дёргать YClients API — только локальный аудит БД",
        )

    def handle(self, *args, skip_yclients_call: bool = False, **options):
        # 1. Локальный аудит — у кого нет yclients_staff_id
        active_masters = list(Master.objects.filter(is_active=True).order_by("order", "name"))
        missing = [m for m in active_masters if not m.yclients_staff_id]
        filled = [m for m in active_masters if m.yclients_staff_id]

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n[*]Активных мастеров в БД: {len(active_masters)}"))
        self.stdout.write(f"  [OK] С yclients_staff_id: {len(filled)}")
        self.stdout.write(f"  [!!] Без yclients_staff_id: {len(missing)}")

        if missing:
            self.stdout.write(self.style.WARNING(
                "\nWARN: Мастера БЕЗ маппинга на YClients (AI native booking невозможен):"))
            for m in missing:
                self.stdout.write(f"  - #{m.id} {m.name} ({m.specialization or '—'})")
            self.stdout.write(self.style.WARNING(
                "\n  Заполнить: /admin/services_app/master/<id>/change/ -> "
                "поле «ID сотрудника в YClients»"))

        if filled:
            self.stdout.write(self.style.SUCCESS(
                "\nOK: Мастера с заполненным маппингом:"))
            for m in filled:
                self.stdout.write(f"  - #{m.id} {m.name} -> YClients staff_id={m.yclients_staff_id}")

        if skip_yclients_call:
            self.stdout.write("\n(пропускаю YClients API — флаг --skip-yclients-call)")
            return self._summary(missing, filled)

        # 2. Опционально — сверка с YClients
        try:
            from services_app.yclients_api import get_yclients_api
            api = get_yclients_api()
            yc_staff = api.get_staff()
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.ERROR(
                f"\nERROR: YClients API недоступен: {exc}"))
            self.stdout.write("Сверка с YClients пропущена. Локальный аудит выше.")
            return self._summary(missing, filled)

        yc_ids = {str(s.get("id")) for s in yc_staff if s.get("id")}
        yc_by_id = {str(s.get("id")): s for s in yc_staff}

        # 2a. У нас staff_id указан но в YClients такого нет (orphan)
        orphans = [m for m in filled if m.yclients_staff_id and m.yclients_staff_id not in yc_ids]
        if orphans:
            self.stdout.write(self.style.ERROR(
                "\nCRIT: Master.yclients_staff_id указан, но в YClients такого сотрудника НЕТ:"))
            for m in orphans:
                self.stdout.write(f"  - #{m.id} {m.name} (staff_id={m.yclients_staff_id})")

        # 2b. YClients staff не привязан ни к какому нашему Master
        our_yc_ids = {m.yclients_staff_id for m in filled if m.yclients_staff_id}
        unmapped_yc = [yc_by_id[yc_id] for yc_id in yc_ids if yc_id not in our_yc_ids]
        if unmapped_yc:
            self.stdout.write(self.style.WARNING(
                "\nINFO: В YClients есть сотрудники, не привязанные к Master в БД:"))
            for s in unmapped_yc:
                self.stdout.write(f"  - YClients #{s.get('id')} {s.get('name', '?')} "
                                  f"({s.get('specialization', '—')})")

        return self._summary(missing, filled, orphans, unmapped_yc)

    def _summary(self, missing, filled, orphans=None, unmapped_yc=None):
        problems = len(missing) + len(orphans or []) + len(unmapped_yc or [])
        if problems == 0:
            self.stdout.write(self.style.SUCCESS(
                "\nOK: Audit чистый — все активные мастера готовы к AI native booking."))
        else:
            self.stdout.write(self.style.WARNING(
                f"\nWARN: Всего проблем: {problems}. "
                "Исправьте до запуска Phase 2.3 в проде."))
