"""
Management-команда для живой проверки интеграции с Яндекс.Вебмастером.

Использование:
    python manage.py check_webmaster                              # данные за последние 7 дней
    python manage.py check_webmaster --list-hosts                 # список верифицированных сайтов
    python manage.py check_webmaster --date-from 2026-02-16 --date-to 2026-02-22

Требует в .env:
    YANDEX_WEBMASTER_TOKEN=<OAuth-токен>
    YANDEX_WEBMASTER_HOST_ID=https:yourdomain.ru:443

Получить HOST_ID:
    python manage.py check_webmaster --list-hosts
"""

import datetime

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Диагностика интеграции с Яндекс.Вебмастером (реальный API)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--list-hosts",
            action="store_true",
            default=False,
            help="Вывести список верифицированных сайтов и их host_id",
        )
        parser.add_argument(
            "--date-from",
            type=str,
            default=None,
            metavar="YYYY-MM-DD",
            help="Начало периода (по умолчанию: 7 дней назад)",
        )
        parser.add_argument(
            "--date-to",
            type=str,
            default=None,
            metavar="YYYY-MM-DD",
            help="Конец периода (по умолчанию: вчера)",
        )

    def handle(self, *args, **options):
        from agents.integrations.yandex_webmaster import (
            YandexWebmasterClient,
            YandexWebmasterError,
        )

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
            client = YandexWebmasterClient.from_settings()
        except YandexWebmasterError as exc:
            self.stdout.write(E(f"✗ Ошибка конфигурации: {exc}"))
            self.stdout.write("")
            self.stdout.write(W("Добавьте в .env:"))
            self.stdout.write(W("  YANDEX_WEBMASTER_TOKEN=AgAAAA..."))
            self.stdout.write(W("  YANDEX_WEBMASTER_HOST_ID=https:yourdomain.ru:443"))
            self.stdout.write("")
            self.stdout.write("Получить OAuth-токен (scope: webmaster:info):")
            self.stdout.write("  https://yandex.ru/dev/webmaster/doc/dg/reference/auth.html")
            self.stdout.write("")
            self.stdout.write("Узнать HOST_ID:")
            self.stdout.write("  1. Временно добавьте только YANDEX_WEBMASTER_TOKEN в .env")
            self.stdout.write("  2. Запустите: python manage.py check_webmaster --list-hosts")
            return

        today = datetime.date.today()
        if options["date_from"]:
            date_from = options["date_from"]
            date_to = options["date_to"] or str(today - datetime.timedelta(days=1))
        else:
            date_to = str(today - datetime.timedelta(days=1))
            date_from = str(today - datetime.timedelta(days=7))

        masked_token = client.token[:6] + "..." if len(client.token) >= 6 else "***"
        self.stdout.write(S("✓ Токен и HOST_ID найдены в настройках"))
        self.stdout.write(f"  Токен:    {masked_token}")
        self.stdout.write(f"  Host ID:  {client.host_id}")
        self.stdout.write(f"  Период:   {date_from}  —  {date_to}")

        # ── 2. Получение user_id ─────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 2. Аутентификация / user_id ==="))
        self.stdout.write(sep)

        try:
            uid = client.get_user_id()
            self.stdout.write(S(f"✓ Соединение установлено, user_id = {uid}"))
        except YandexWebmasterError as exc:
            self.stdout.write(E(f"✗ Ошибка: {exc}"))
            if "401" in str(exc):
                self.stdout.write(W("  → Токен недействителен или истёк"))
                self.stdout.write(W("  → Получите новый OAuth-токен на yandex.ru/dev/webmaster"))
            else:
                self.stdout.write(W("  → Проверьте интернет-соединение"))
            return

        # ── 3. Список сайтов ─────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== 3. Верифицированные сайты ==="))
        self.stdout.write(sep)

        try:
            hosts = client.list_hosts()
        except YandexWebmasterError as exc:
            self.stdout.write(E(f"✗ Не удалось получить список сайтов: {exc}"))
            hosts = []

        if not hosts:
            self.stdout.write(W("  Нет верифицированных сайтов в этом аккаунте"))
        else:
            self.stdout.write(f"  Найдено сайтов: {len(hosts)}")
            self.stdout.write("")
            for h in hosts:
                verified = S("✓ верифицирован") if h["verified"] else W("✗ не верифицирован")
                match = S("[MATCH]") if h["host_id"] == client.host_id else "       "
                self.stdout.write(f"  {match}  {verified}  {h['url']}")
                self.stdout.write(f"           host_id: {h['host_id']}")
                self.stdout.write("")

            if not any(h["host_id"] == client.host_id for h in hosts):
                self.stdout.write(W(f"  HOST_ID '{client.host_id}' не найден в списке."))
                self.stdout.write(W("  → Обновите YANDEX_WEBMASTER_HOST_ID в .env"))
                if hosts:
                    suggest = hosts[0]
                    self.stdout.write(
                        W(f"  → Например: YANDEX_WEBMASTER_HOST_ID={suggest['host_id']}")
                    )

        if options["list_hosts"]:
            self.stdout.write("\n" + sep)
            self.stdout.write(S("=== Готово ==="))
            self.stdout.write(sep)
            self.stdout.write("Скопируйте нужный host_id в .env:")
            self.stdout.write("  YANDEX_WEBMASTER_HOST_ID=<host_id из списка выше>")
            self.stdout.write("")
            return

        # ── 4. Топ страниц ───────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H(f"=== 4. Топ-10 страниц ({date_from} — {date_to}) ==="))
        self.stdout.write(sep)

        try:
            pages = client.get_top_pages(date_from, date_to, limit=10)
        except YandexWebmasterError as exc:
            self.stdout.write(E(f"✗ Ошибка получения страниц: {exc}"))
            pages = []

        if not pages:
            self.stdout.write(W("  Нет данных по страницам за указанный период"))
        else:
            self.stdout.write(
                f"  {'URL':<45} {'Клики':>7} {'Показы':>8} {'CTR':>6} {'Позиция':>8}"
            )
            self.stdout.write("  " + "-" * 78)
            for p in pages[:10]:
                url = p["url"][-44:] if len(p["url"]) > 44 else p["url"]
                self.stdout.write(
                    f"  {url:<45} {p['clicks']:>7,} {p['impressions']:>8,} "
                    f"{p['ctr']:.1%}  {p['avg_position']:>7.1f}"
                )

        # ── 5. Топ запросов ──────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H(f"=== 5. Топ-10 запросов ({date_from} — {date_to}) ==="))
        self.stdout.write(sep)

        try:
            queries = client.get_top_queries(date_from, date_to, limit=10)
        except YandexWebmasterError as exc:
            self.stdout.write(E(f"✗ Ошибка получения запросов: {exc}"))
            queries = []

        if not queries:
            self.stdout.write(W("  Нет данных по запросам за указанный период"))
        else:
            self.stdout.write(
                f"  {'Запрос':<40} {'Клики':>7} {'Показы':>8} {'CTR':>6} {'Позиция':>8}"
            )
            self.stdout.write("  " + "-" * 73)
            for q in queries[:10]:
                qtext = q["query"][:39] if len(q["query"]) > 39 else q["query"]
                self.stdout.write(
                    f"  {qtext:<40} {q['clicks']:>7,} {q['impressions']:>8,} "
                    f"{q['ctr']:.1%}  {q['avg_position']:>7.1f}"
                )

        # ── Итог ─────────────────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== Итог ==="))
        self.stdout.write(sep)

        if pages or queries:
            self.stdout.write(S("✓ Интеграция с Яндекс.Вебмастером работает корректно"))
            self.stdout.write(
                "  → Данные будут загружаться еженедельно в SEOLandingAgent (пн 08:00)"
            )
            self.stdout.write(
                "  → Запустить агент вручную: python manage.py shell -c "
                '"from agents.agents.seo_landing import SEOLandingAgent; '
                'SEOLandingAgent().run()"'
            )
        else:
            self.stdout.write(W("  Данные не получены — проверьте HOST_ID и период"))
        self.stdout.write("")
