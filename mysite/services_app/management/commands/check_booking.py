"""
Management-команда для диагностики бронирования через YClients API.

Использование:
    python manage.py check_booking
    python manage.py check_booking --staff-id 4416525
    python manage.py check_booking --yclients-service-id 99999
    python manage.py check_booking --date 2026-03-01
    python manage.py check_booking --staff-id 4416525 --date 2026-03-01
"""

import datetime
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Диагностика бронирования: ServiceOptions в БД + мастера/даты/слоты из YClients"

    def add_arguments(self, parser):
        parser.add_argument(
            "--staff-id",
            type=int,
            default=None,
            help="ID мастера в YClients (если не указан — берётся первый из списка)",
        )
        parser.add_argument(
            "--yclients-service-id",
            type=int,
            default=None,
            help="ID услуги в YClients (фильтровать мастеров по услуге)",
        )
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Дата в формате YYYY-MM-DD (если не указана — берётся первая доступная)",
        )

    def handle(self, *args, **options):
        from services_app.models import ServiceOption
        from services_app.yclients_api import get_yclients_api, YClientsAPIError

        W = self.style.WARNING
        S = self.style.SUCCESS
        E = self.style.ERROR

        # ── 1. ServiceOptions в БД ──────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.MIGRATE_HEADING("=== ServiceOptions в БД ==="))
        self.stdout.write("=" * 60)

        options_qs = ServiceOption.objects.filter(is_active=True).select_related("service").order_by("id")
        total = options_qs.count()
        with_id = options_qs.exclude(yclients_service_id__isnull=True).exclude(yclients_service_id="")
        without_id = options_qs.filter(yclients_service_id__isnull=True) | options_qs.filter(yclients_service_id="")

        self.stdout.write(f"Всего активных: {total}   [OK] {with_id.count()}   [MISS] {without_id.count()}\n")

        for opt in options_qs[:30]:
            has = bool(opt.yclients_service_id)
            tag = S("[OK  ]") if has else E("[MISS]")
            yid = opt.yclients_service_id or "—"
            self.stdout.write(f"  {tag}  id={opt.id:<4}  yclients_id={yid:<10}  {opt}")

        if total > 30:
            self.stdout.write(f"  ... и ещё {total - 30} записей")

        # ── 2. YClients API — инициализация ────────────────────────────────
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.MIGRATE_HEADING("=== YClients API ==="))
        self.stdout.write("=" * 60)

        try:
            api = get_yclients_api()
            self.stdout.write(S("✓ API клиент создан"))
            self.stdout.write(f"  company_id    = {api.company_id}")
            self.stdout.write(f"  partner_token = {api.partner_token[:8]}...")
            self.stdout.write(f"  user_token    = {api.user_token[:8]}...")
        except Exception as exc:
            self.stdout.write(E(f"✗ Ошибка инициализации API: {exc}"))
            return

        # ── 3. Список мастеров ─────────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)
        yclients_service_id = options["yclients_service_id"]
        if yclients_service_id:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"=== Мастера для услуги yclients_service_id={yclients_service_id} ==="
            ))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING("=== Все мастера (без фильтра по услуге) ==="))
        self.stdout.write("=" * 60)

        try:
            staff_list = api.get_staff(service_id=yclients_service_id)
        except Exception as exc:
            self.stdout.write(E(f"✗ get_staff() упал: {exc}"))
            staff_list = []

        if not staff_list:
            self.stdout.write(E("  Мастеров не найдено!"))
            self.stdout.write(W("  Возможные причины:"))
            self.stdout.write(W("    - IP заблокирован WAF YClients (попробуйте с другой сети)"))
            self.stdout.write(W("    - Токен не имеет прав на чтение"))
            self.stdout.write(W("    - В YClients нет мастеров для данной услуги"))
        else:
            self.stdout.write(S(f"  Найдено мастеров: {len(staff_list)}"))
            for s in staff_list:
                self.stdout.write(f"    id={s.get('id'):<10}  {s.get('name', '—')}")

        # ── 4. Доступные даты ──────────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)

        staff_id = options["staff_id"]
        if not staff_id and staff_list:
            staff_id = staff_list[0]["id"]

        if not staff_id:
            self.stdout.write(E("Мастер не определён, пропускаем даты и слоты."))
            self.stdout.write(W("Укажите --staff-id вручную или убедитесь, что список мастеров не пустой."))
            return

        staff_name = next(
            (s["name"] for s in staff_list if s.get("id") == staff_id),
            f"id={staff_id}"
        )

        self.stdout.write(self.style.MIGRATE_HEADING(f"=== Доступные даты ({staff_name}, id={staff_id}) ==="))
        self.stdout.write("=" * 60)

        try:
            dates = api.get_book_dates(staff_id=staff_id)
        except Exception as exc:
            self.stdout.write(E(f"✗ get_book_dates() упал: {exc}"))
            dates = []

        if not dates:
            self.stdout.write(E("  Нет доступных дат"))
        else:
            self.stdout.write(S(f"  Найдено дат: {len(dates)}"))
            preview = dates[:10]
            self.stdout.write("  " + "  ".join(preview))
            if len(dates) > 10:
                self.stdout.write(f"  ... и ещё {len(dates) - 10}")

        # ── 5. Свободные слоты ────────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)

        target_date = options["date"]
        if not target_date and dates:
            target_date = dates[0]

        if not target_date:
            self.stdout.write(E("Дата не определена, пропускаем слоты."))
            self.stdout.write(W("Укажите --date YYYY-MM-DD или убедитесь, что даты не пустые."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"=== Свободные слоты ({staff_name}, {target_date}) ==="
        ))
        self.stdout.write("=" * 60)

        try:
            times = api.get_available_times(staff_id=staff_id, date=target_date)
        except Exception as exc:
            self.stdout.write(E(f"✗ get_available_times() упал: {exc}"))
            times = []

        if not times:
            self.stdout.write(E(f"  Нет свободных слотов на {target_date}"))
        else:
            self.stdout.write(S(f"  Найдено слотов: {len(times)}"))
            row = []
            for i, t in enumerate(times):
                row.append(t)
                if len(row) == 8:
                    self.stdout.write("  " + "  ".join(row))
                    row = []
            if row:
                self.stdout.write("  " + "  ".join(row))

        # ── Итог ──────────────────────────────────────────────────────────
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.MIGRATE_HEADING("=== Итог ==="))
        self.stdout.write("=" * 60)
        self.stdout.write(f"  ServiceOptions с yclients_service_id: {with_id.count()}/{total}")
        self.stdout.write(f"  Мастеров в YClients: {len(staff_list)}")
        self.stdout.write(f"  Доступных дат для {staff_name}: {len(dates)}")
        self.stdout.write(f"  Слотов на {target_date}: {len(times)}")

        if with_id.count() == 0:
            self.stdout.write("")
            self.stdout.write(E("! НИ У ОДНОГО ServiceOption нет yclients_service_id"))
            self.stdout.write(W("  → Заполните в Django Admin: /admin/services_app/serviceoption/"))
            self.stdout.write(W("    Поле: «ID услуги в YCLIENTS»"))
        elif len(staff_list) == 0:
            self.stdout.write("")
            self.stdout.write(E("! Мастера не получены из YClients"))
            self.stdout.write(W("  → Скорее всего IP заблокирован WAF. Попробуйте с другой сети."))
        else:
            self.stdout.write("")
            self.stdout.write(S("✓ API работает. Для получения слотов по услуге запустите:"))
            if with_id.exists():
                first_opt = with_id.first()
                self.stdout.write(
                    f"  python manage.py check_booking"
                    f" --yclients-service-id {first_opt.yclients_service_id}"
                )
