"""
Применяет SEO-аудит: обновляет seo_title, seo_h1, seo_description
для услуг и категорий по данным из _seo_audit_data.py.

Использование:
    python manage.py apply_seo_audit --dry-run   # показать что изменится
    python manage.py apply_seo_audit              # применить
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Применяет SEO-тексты из аудита для 58 услуг и 13 категорий"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true", default=False,
            help="Только показать что изменится, без записи в БД",
        )

    def handle(self, *args, **options):
        from services_app.models import Service, ServiceCategory
        from agents.management.commands._seo_audit_data import (
            CATEGORIES_SEO,
            SERVICES_SEO,
        )

        S = self.style.SUCCESS
        E = self.style.ERROR
        W = self.style.WARNING
        H = self.style.MIGRATE_HEADING
        dry = options["dry_run"]
        sep = "=" * 60

        if dry:
            self.stdout.write(W("\n  *** DRY RUN — ничего не записывается ***\n"))

        # ── Услуги ────────────────────────────────────────────────────
        self.stdout.write(H(f"\n{sep}\n=== Услуги ({len(SERVICES_SEO)} записей) ===\n{sep}"))
        svc_ok = 0
        svc_skip = 0
        svc_miss = []

        for slug, seo in SERVICES_SEO.items():
            try:
                service = Service.objects.get(slug=slug)
            except Service.DoesNotExist:
                svc_miss.append(slug)
                continue

            changed = []
            for field in ("seo_title", "seo_h1", "seo_description"):
                old = getattr(service, field, "")
                new = seo[field]
                if old != new:
                    changed.append(field)

            if not changed:
                svc_skip += 1
                continue

            if not dry:
                Service.objects.filter(slug=slug).update(**{f: seo[f] for f in changed})

            svc_ok += 1
            self.stdout.write(S(f"  [UPD] {slug}: {', '.join(changed)}"))

        self.stdout.write(f"\n  Обновлено: {svc_ok}, без изменений: {svc_skip}")
        if svc_miss:
            self.stdout.write(E(f"  Не найдено на проде ({len(svc_miss)}):"))
            for s in svc_miss:
                self.stdout.write(E(f"    - {s}"))

        # ── Категории ─────────────────────────────────────────────────
        self.stdout.write(H(f"\n{sep}\n=== Категории ({len(CATEGORIES_SEO)} записей) ===\n{sep}"))
        cat_ok = 0
        cat_skip = 0
        cat_miss = []

        for slug, seo in CATEGORIES_SEO.items():
            try:
                cat = ServiceCategory.objects.get(slug=slug)
            except ServiceCategory.DoesNotExist:
                cat_miss.append(slug)
                continue

            changed = []
            for field in ("seo_title", "seo_h1", "seo_description"):
                old = getattr(cat, field, "")
                new = seo[field]
                if old != new:
                    changed.append(field)

            if not changed:
                cat_skip += 1
                continue

            if not dry:
                ServiceCategory.objects.filter(slug=slug).update(
                    **{f: seo[f] for f in changed}
                )

            cat_ok += 1
            self.stdout.write(S(f"  [UPD] {slug}: {', '.join(changed)}"))

        self.stdout.write(f"\n  Обновлено: {cat_ok}, без изменений: {cat_skip}")
        if cat_miss:
            self.stdout.write(E(f"  Не найдено на проде ({len(cat_miss)}):"))
            for s in cat_miss:
                self.stdout.write(E(f"    - {s}"))

        # ── Итог ──────────────────────────────────────────────────────
        self.stdout.write(H(f"\n{sep}\n=== Итог ===\n{sep}"))
        total = svc_ok + cat_ok
        missed = len(svc_miss) + len(cat_miss)
        if dry:
            self.stdout.write(W(f"  DRY RUN: {total} записей будет обновлено, {missed} не найдено"))
        else:
            self.stdout.write(S(f"  Обновлено: {total} записей, не найдено: {missed}"))
        self.stdout.write("")
