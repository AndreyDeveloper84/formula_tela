"""
Показывает структуру записей YClients для отладки полей выручки.

Использование:
    python manage.py debug_yclients_records               # 5 последних записей за 7 дней
    python manage.py debug_yclients_records --count 10    # 10 записей
    python manage.py debug_yclients_records --days 30     # за 30 дней

Цель: определить в каком поле YClients возвращает фактическую выручку
(sum, amount, cost, services[i].cost, services[i].first_cost и т.д.).
"""
import datetime
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Показывает структуру записей YClients (отладка полей выручки)"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=5)
        parser.add_argument("--days", type=int, default=7)

    def handle(self, *args, **options):
        from services_app.yclients_api import get_yclients_api, YClientsAPIError

        S = self.style.SUCCESS
        E = self.style.ERROR
        W = self.style.WARNING
        H = self.style.MIGRATE_HEADING
        sep = "=" * 70

        try:
            api = get_yclients_api()
        except Exception as exc:
            self.stdout.write(E(f"Ошибка конфигурации YClients: {exc}"))
            return

        today = datetime.date.today()
        start = today - datetime.timedelta(days=options["days"])
        self.stdout.write(H(f"\n{sep}\n=== YClients records: {start} - {today} ===\n{sep}"))

        try:
            records = api.get_records(str(start), str(today), count=options["count"])
        except Exception as exc:
            self.stdout.write(E(f"Ошибка API: {exc}"))
            return

        if not records:
            self.stdout.write(W("Нет записей за указанный период"))
            return

        self.stdout.write(f"Получено записей: {len(records)}\n")

        # Собираем все уникальные ключи на корневом уровне
        root_keys = set()
        svc_keys = set()
        client_keys = set()
        for r in records:
            root_keys.update(r.keys())
            for s in r.get("services") or []:
                svc_keys.update(s.keys())
            c = r.get("client") or {}
            client_keys.update(c.keys())

        self.stdout.write(H(f"\n--- Все ключи корневого уровня записи ---"))
        self.stdout.write(", ".join(sorted(root_keys)))
        self.stdout.write(H(f"\n--- Все ключи services[] ---"))
        self.stdout.write(", ".join(sorted(svc_keys)))
        self.stdout.write(H(f"\n--- Все ключи client{{}} ---"))
        self.stdout.write(", ".join(sorted(client_keys)))

        # Кандидаты на поле выручки
        revenue_candidates = [
            "sum", "amount", "total", "cost", "total_cost",
            "paid_full", "price", "revenue",
        ]
        svc_revenue_candidates = [
            "cost", "amount", "first_cost", "price", "price_min",
            "price_max", "cost_per_unit", "discount",
        ]

        self.stdout.write(H(f"\n{sep}\n=== Детальный разбор записей ===\n{sep}\n"))

        for i, rec in enumerate(records[:options["count"]], 1):
            self.stdout.write(H(f"--- Запись #{i} (id={rec.get('id', '?')}) ---"))
            self.stdout.write(f"  date:     {rec.get('date')}")
            self.stdout.write(f"  datetime: {rec.get('datetime')}")

            # Статус
            status = rec.get("status") or {}
            self.stdout.write(f"  status:   id={status.get('id')} title={status.get('title')}")
            self.stdout.write(f"  deleted:  {rec.get('deleted')}")
            self.stdout.write(f"  attendance: {rec.get('visit_attendance')}")

            # Revenue-кандидаты на корневом уровне
            self.stdout.write(W("\n  Revenue-кандидаты (корень):"))
            for field in revenue_candidates:
                val = rec.get(field)
                if val is not None:
                    self.stdout.write(S(f"    {field}: {val!r}  (type={type(val).__name__})"))
                else:
                    self.stdout.write(f"    {field}: None / отсутствует")

            # Клиент
            client = rec.get("client") or {}
            self.stdout.write(W("\n  Client:"))
            for k in ["id", "name", "phone", "email"]:
                self.stdout.write(f"    {k}: {client.get(k, '—')}")

            # Мастер
            staff = rec.get("staff") or {}
            self.stdout.write(f"\n  Staff: id={staff.get('id')} name={staff.get('name')}")

            # Услуги (с revenue-кандидатами)
            services = rec.get("services") or []
            self.stdout.write(W(f"\n  Services ({len(services)}):"))
            for j, svc in enumerate(services, 1):
                title = svc.get("title") or svc.get("name") or "?"
                self.stdout.write(f"    [{j}] {title}")
                for field in svc_revenue_candidates:
                    val = svc.get(field)
                    if val is not None:
                        self.stdout.write(S(f"        {field}: {val!r}  (type={type(val).__name__})"))

            self.stdout.write("")

        # Итоговая сводка
        self.stdout.write(H(f"\n{sep}\n=== Сводка по revenue ===\n{sep}"))
        total_root_sum = 0
        total_svc_cost = 0
        total_svc_first_cost = 0
        total_svc_amount = 0
        for rec in records:
            total_root_sum += float(rec.get("sum") or 0)
            for svc in rec.get("services") or []:
                total_svc_cost += float(svc.get("cost") or 0)
                total_svc_first_cost += float(svc.get("first_cost") or 0)
                total_svc_amount += float(svc.get("amount") or 0)

        self.stdout.write(f"  record.sum total:            {total_root_sum:,.0f}")
        self.stdout.write(f"  services[].cost total:       {total_svc_cost:,.0f}")
        self.stdout.write(f"  services[].first_cost total: {total_svc_first_cost:,.0f}")
        self.stdout.write(f"  services[].amount total:     {total_svc_amount:,.0f}")

        winner = max(
            [("record.sum", total_root_sum),
             ("services[].cost", total_svc_cost),
             ("services[].first_cost", total_svc_first_cost),
             ("services[].amount", total_svc_amount)],
            key=lambda x: x[1],
        )
        if winner[1] > 0:
            self.stdout.write(S(f"\n  >>> Используйте поле: {winner[0]} ({winner[1]:,.0f} руб.)"))
        else:
            self.stdout.write(E("\n  >>> Все поля = 0. Проверьте статус записей и права API-токена."))
        self.stdout.write("")
