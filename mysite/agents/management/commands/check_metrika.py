"""
Management-команда для живой проверки интеграции с Яндекс.Метрикой.

Использование:
    python manage.py check_metrika                          # последние 30 дней
    python manage.py check_metrika --period 7               # последние 7 дней
    python manage.py check_metrika --period 90              # последние 90 дней
    python manage.py check_metrika --date-from 2026-01-01 --date-to 2026-01-31

Требует в .env:
    YANDEX_METRIKA_TOKEN=<OAuth-токен>
    YANDEX_METRIKA_COUNTER_ID=<числовой ID счётчика>
"""

import datetime

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Диагностика интеграции с Яндекс.Метрикой (реальный API)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            type=int,
            default=30,
            metavar="DAYS",
            help="Количество дней назад от сегодня (по умолчанию: 30)",
        )
        parser.add_argument(
            "--date-from",
            type=str,
            default=None,
            metavar="YYYY-MM-DD",
            help="Начало периода (если задано — перекрывает --period)",
        )
        parser.add_argument(
            "--date-to",
            type=str,
            default=None,
            metavar="YYYY-MM-DD",
            help="Конец периода (по умолчанию: сегодня)",
        )

    def handle(self, *args, **options):
        from agents.integrations.yandex_metrika import YandexMetrikaClient, YandexMetrikaError

        S = self.style.SUCCESS
        E = self.style.ERROR
        W = self.style.WARNING
        H = self.style.MIGRATE_HEADING

        sep = "=" * 60

        # ── 1. Конфигурация ──────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 1. Конфигурация ==="))
        self.stdout.write(sep)

        try:
            client = YandexMetrikaClient.from_settings()
        except YandexMetrikaError as exc:
            self.stdout.write(E(f"✗ Ошибка конфигурации: {exc}"))
            self.stdout.write("")
            self.stdout.write(W("Добавьте в .env:"))
            self.stdout.write(W("  YANDEX_METRIKA_TOKEN=AgAAAA..."))
            self.stdout.write(W("  YANDEX_METRIKA_COUNTER_ID=12345678"))
            self.stdout.write("")
            self.stdout.write("Получить токен:")
            self.stdout.write(
                "  https://oauth.yandex.ru/authorize?response_type=token"
                "&client_id=1d0b9dd4d652455a9eb710d450ff456a"
            )
            self.stdout.write("Counter ID: Метрика → Настройки → Номер счётчика")
            return

        # Определяем период
        today = datetime.date.today()
        if options["date_from"]:
            date_from = options["date_from"]
            date_to = options["date_to"] or str(today)
        else:
            days = options["period"]
            date_from = str(today - datetime.timedelta(days=days))
            date_to = str(today)

        masked_token = client.token[:6] + "..." if len(client.token) >= 6 else "***"
        self.stdout.write(S("✓ Токен и Counter ID найдены в настройках"))
        self.stdout.write(f"  Токен:      {masked_token}")
        self.stdout.write(f"  Counter ID: {client.counter_id}")
        self.stdout.write(f"  Период:     {date_from}  —  {date_to}")

        # ── 2. Тест подключения ──────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 2. Подключение к API ==="))
        self.stdout.write(sep)

        try:
            # Минимальный запрос: одна метрика, один день
            client._request({
                "id": client.counter_id,
                "metrics": "ym:s:visits",
                "date1": date_to,
                "date2": date_to,
            })
            self.stdout.write(S("✓ Соединение с api-metrika.yandex.net установлено"))
        except YandexMetrikaError as exc:
            self.stdout.write(E(f"✗ Ошибка соединения: {exc}"))
            self.stdout.write("")
            if "401" in str(exc):
                self.stdout.write(W("  → Токен недействителен или истёк"))
                self.stdout.write(W("  → Получите новый на oauth.yandex.ru"))
            elif "403" in str(exc):
                self.stdout.write(W(f"  → Нет доступа к счётчику {client.counter_id}"))
                self.stdout.write(W("  → Убедитесь, что токен выдан для нужного аккаунта"))
                self.stdout.write(W("  → Counter ID — число (не строка): Метрика → Настройки"))
            else:
                self.stdout.write(W("  → Проверьте интернет-соединение и настройки прокси"))
            return

        # ── 3. Сводная статистика ────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 3. Сводная статистика ==="))
        self.stdout.write(sep)

        try:
            result = client.get_summary(date1=date_from, date2=date_to)
        except YandexMetrikaError as exc:
            self.stdout.write(E(f"✗ get_summary() упал: {exc}"))
            return

        sessions     = result.get("sessions", 0)
        bounce_rate  = result.get("bounce_rate", 0.0)
        goal_reaches = result.get("goal_reaches", 0)
        page_depth   = result.get("page_depth", 0.0)

        self.stdout.write(f"  Сессий:              {sessions:>10,}")
        self.stdout.write(f"  Показатель отказов:  {bounce_rate:>9.1f}%")
        self.stdout.write(f"  Достижение целей:    {goal_reaches:>10,}")
        self.stdout.write(f"  Глубина просмотра:   {page_depth:>9.2f} стр.")

        if sessions == 0:
            self.stdout.write("")
            self.stdout.write(W("  Сессий = 0. Возможные причины:"))
            self.stdout.write(W("  - Счётчик установлен недавно и данных ещё нет"))
            self.stdout.write(W("  - Counter ID неверный (принадлежит другому сайту)"))
            self.stdout.write(W("  - В выбранный период сайт не получал трафик"))

        # ── 4. Топ-5 источников трафика ──────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 4. Топ-5 источников трафика ==="))
        self.stdout.write(sep)

        top_sources = result.get("top_sources", [])
        if not top_sources:
            self.stdout.write(W("  Нет данных об источниках трафика"))
        else:
            for i, src in enumerate(top_sources, start=1):
                name   = src.get("source", "?")
                visits = src.get("visits", 0)
                bar    = "█" * min(int(visits / max(top_sources[0].get("visits", 1) / 20, 1)), 20)
                self.stdout.write(f"  {i}. {name:<15} — {visits:>6,} визитов  {bar}")

        # ── Итог ─────────────────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== Итог ==="))
        self.stdout.write(sep)

        self.stdout.write(S("✓ Интеграция с Яндекс.Метрикой работает корректно"))
        self.stdout.write(
            f"  → Данные за последние 30 дней будут поступать в AnalyticsBudgetAgent (09:00)"
        )
        self.stdout.write(
            f"  → Запустить агент вручную: python manage.py shell -c "
            '"from agents.agents.analytics_budget import AnalyticsBudgetAgent; '
            'AnalyticsBudgetAgent().gather_data()"'
        )
        self.stdout.write("")
