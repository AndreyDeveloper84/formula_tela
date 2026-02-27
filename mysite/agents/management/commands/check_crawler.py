"""
Management-команда для запуска TechnicalSEOWatchdog.

Использование:
    python manage.py check_crawler                  # полная проверка
    python manage.py check_crawler --urls-only      # только проверка страниц
    python manage.py check_crawler --sitemap-only   # только проверка sitemap
    python manage.py check_crawler --no-db          # без создания SeoTask в БД

Требует в .env:
    SITE_BASE_URL=https://formulatela.ru
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Технический SEO-аудит: проверка доступности страниц и sitemap.xml"

    def add_arguments(self, parser):
        parser.add_argument(
            "--urls-only",
            action="store_true",
            default=False,
            help="Проверить только страницы услуг (без sitemap)",
        )
        parser.add_argument(
            "--sitemap-only",
            action="store_true",
            default=False,
            help="Проверить только sitemap.xml (без страниц)",
        )
        parser.add_argument(
            "--no-db",
            action="store_true",
            default=False,
            help="Не создавать SeoTask в БД (только вывод в консоль)",
        )

    def handle(self, *args, **options):
        from agents.integrations.site_crawler import (
            TechnicalSEOWatchdog,
            TechnicalSEOError,
        )

        S = self.style.SUCCESS
        E = self.style.ERROR
        W = self.style.WARNING
        H = self.style.MIGRATE_HEADING
        sep = "=" * 60

        # ── Конфигурация ─────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== TechnicalSEOWatchdog ==="))
        self.stdout.write(sep)

        try:
            watchdog = TechnicalSEOWatchdog.from_settings()
        except TechnicalSEOError as exc:
            self.stdout.write(E(f"Oshibka konfiguratsii: {exc}"))
            self.stdout.write(W("Dobavte v .env:"))
            self.stdout.write(W("  SITE_BASE_URL=https://formulatela.ru"))
            return

        self.stdout.write(S(f"base_url: {watchdog.base_url}"))
        self.stdout.write(f"  timeout: {watchdog.timeout} sek")
        if options["no_db"]:
            self.stdout.write(W("  --no-db: SeoTask sozdavatsya NE budut"))

        urls_only = options["urls_only"]
        sitemap_only = options["sitemap_only"]

        # ── Проверка страниц ─────────────────────────────────────────
        if not sitemap_only:
            self.stdout.write("\n" + sep)
            self.stdout.write(H("=== Proverka stranits uslug ==="))
            self.stdout.write(sep)

            urls = watchdog.get_all_service_urls()
            self.stdout.write(f"  Aktivnyh uslug v BD: {len(urls)}")

            if not urls:
                self.stdout.write(W("  Net aktivnyh uslug so slug — proverte BD"))
            else:
                self.stdout.write("  Proveryayu stranitsy...")

                if options["no_db"]:
                    # В режиме --no-db не создаём SeoTask
                    results = [watchdog._check_url(u) for u in urls]
                else:
                    results = watchdog.check_service_pages(urls)

                ok_count = sum(1 for r in results if not r["issue"])
                err_count = sum(1 for r in results if r["issue"])

                self.stdout.write(f"\n  {'URL':<55} {'Status':>7} {'Problema'}")
                self.stdout.write("  " + "-" * 75)
                for r in sorted(results, key=lambda x: x["status_code"]):
                    short_url = r["url"].replace(watchdog.base_url, "")
                    if r["issue"]:
                        line = f"  {short_url:<55} {r['status_code']:>7}  {r['issue']}"
                        self.stdout.write(E(line))
                    else:
                        line = f"  {short_url:<55} {r['status_code']:>7}  OK"
                        self.stdout.write(S(line))

                self.stdout.write("")
                self.stdout.write(S(f"  Dostupno: {ok_count}"))
                if err_count:
                    self.stdout.write(E(f"  Problem: {err_count}"))
                    if not options["no_db"]:
                        self.stdout.write(
                            W("  -> Sozdany/najdeny SeoTask v BD")
                        )
                        self.stdout.write(
                            W("  -> Smotri: /admin/agents/seotask/?status=open")
                        )

        # ── Проверка sitemap ─────────────────────────────────────────
        if not urls_only:
            self.stdout.write("\n" + sep)
            self.stdout.write(H("=== Proverka sitemap.xml ==="))
            self.stdout.write(sep)

            sitemap = watchdog.check_sitemap()
            self.stdout.write(f"  URL: {sitemap['sitemap_url']}")

            if not sitemap["sitemap_available"]:
                self.stdout.write(E(f"  Sitemap nedostupen: {sitemap['error']}"))
                self.stdout.write(W("  -> Proverte chto sitemap.xml suschestvuet"))
                self.stdout.write(W("  -> Obychno nastraivaetsya cherez django.contrib.sitemaps"))
            else:
                self.stdout.write(S("  Sitemap zagruzhen"))
                self.stdout.write(f"  Vsego URL v sitemap:  {sitemap['sitemap_total']}")
                self.stdout.write(f"  Aktivnyh uslug v BD:  {sitemap['service_urls_in_db']}")

                missing = sitemap["missing_from_sitemap"]
                extra = sitemap["extra_in_sitemap"]

                if missing:
                    self.stdout.write(
                        E(f"\n  Otsutstvuyut v sitemap ({len(missing)} stranits):")
                    )
                    for url in missing[:20]:
                        self.stdout.write(E(f"    - {url}"))
                    self.stdout.write(
                        W("  -> Dobavte eti URL v sitemap (Yandex ih ne proindeksiruet)")
                    )
                else:
                    self.stdout.write(S("  Vse stranitsy uslug est v sitemap"))

                if extra:
                    self.stdout.write(
                        W(f"\n  Lishnie URL v sitemap ({len(extra)} stranits):")
                    )
                    for url in extra[:20]:
                        self.stdout.write(W(f"    - {url}"))
                    self.stdout.write(
                        W("  -> Eti URL dayut 404 ili vedut na udalyonnye uslugi")
                    )
                else:
                    self.stdout.write(S("  Lishnih URL v sitemap net"))

        # ── Итог ─────────────────────────────────────────────────────
        self.stdout.write("\n" + sep)
        self.stdout.write(H("=== Itog ==="))
        self.stdout.write(sep)
        self.stdout.write(S("Watchdog zavershen"))
        self.stdout.write(
            "  -> Zapuskat ezhenedelno ili posle kazhdogo deploya"
        )
        self.stdout.write(
            "  -> Otkrytye zadachi: /admin/agents/seotask/?status=open"
        )
        self.stdout.write("")
