"""
Management command: fill_related_services
Автоматически заполняет related_services для услуг без перелинковки.

Стратегия:
- Для каждой услуги без related_services находит до 5 услуг той же категории
- Приоритет: популярные → с ценой → по названию
- Не перезаписывает уже настроенные связи если не передан --force

Использование:
    python manage.py fill_related_services
    python manage.py fill_related_services --force
    python manage.py fill_related_services --dry-run
    python manage.py fill_related_services --category lazernaya-epilyaciya
"""
from django.core.management.base import BaseCommand

from services_app.models import Service

MAX_RELATED = 5


class Command(BaseCommand):
    help = "Заполняет related_services для услуг без перелинковки (по категории)"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Перезаписать даже если related_services уже есть")
        parser.add_argument("--dry-run", action="store_true",
                            help="Только показать, не сохранять")
        parser.add_argument("--category", type=str, default=None,
                            help="Ограничить по slug категории")
        parser.add_argument("--max", type=int, default=MAX_RELATED,
                            help=f"Максимум связанных услуг (по умолчанию {MAX_RELATED})")

    def handle(self, *args, **options):
        force = options["force"]
        dry_run = options["dry_run"]
        cat_filter = options["category"]
        max_rel = options["max"]

        qs = Service.objects.filter(is_active=True).select_related("category")
        if cat_filter:
            qs = qs.filter(category__slug=cat_filter)

        updated = skipped = 0

        for svc in qs:
            if not force and svc.related_services.exists():
                skipped += 1
                continue

            if not svc.category_id:
                skipped += 1
                continue

            # Услуги той же категории, кроме самой себя
            candidates = (
                Service.objects
                .filter(is_active=True, category_id=svc.category_id)
                .exclude(pk=svc.pk)
                .prefetch_related("options")
                .order_by("-is_popular", "order", "name")
            )[:max_rel]

            if not candidates:
                skipped += 1
                continue

            if dry_run:
                names = ", ".join(c.name for c in candidates)
                self.stdout.write(f"[{svc.id}] {svc.name} → [{names}]")
            else:
                svc.related_services.set(candidates)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ [{svc.id}] {svc.name} → {candidates.count()} услуг"
                    )
                )
            updated += 1

        mode = "DRY RUN" if dry_run else "SAVED"
        self.stdout.write(f"\n[{mode}] Обновлено: {updated}, пропущено: {skipped}")
