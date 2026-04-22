"""Custom QuerySet classes для services_app.

Использование:
    Service.objects.active().popular().with_options().with_category()
    ServiceCategory.objects.with_active_services()
    Bundle.objects.active().with_items()

Все методы возвращают QuerySet → чейнинг безопасен.
"""
from django.db import models
from django.db.models import Prefetch


class ServiceQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)

    def popular(self):
        return self.filter(is_popular=True)

    def with_category(self):
        return self.select_related("category")

    def with_options(self):
        from services_app.models import ServiceOption
        options_qs = ServiceOption.objects.active().ordered()
        return self.prefetch_related(Prefetch("options", queryset=options_qs))

    def with_slug(self):
        return self.filter(slug__isnull=False).exclude(slug="")

    def ordered(self):
        # Service.Meta.ordering закомментирован — сортируем явно.
        return self.order_by("order", "name")


class ServiceOptionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def ordered(self):
        return self.order_by("order", "duration_min", "unit_type", "units")

    def for_service(self, service):
        return self.filter(service=service)


class ServiceCategoryQuerySet(models.QuerySet):
    def active(self):
        """Только видимые категории (is_active=True)."""
        return self.filter(is_active=True)

    def with_active_services(self):
        from services_app.models import Service
        return self.active().prefetch_related(
            Prefetch("services", queryset=Service.objects.active())
        ).filter(services__is_active=True).distinct()

    def by_slug(self, slug):
        return self.filter(slug=slug)


class MasterQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_services(self):
        return self.prefetch_related("services")

    def with_services_and_options(self):
        return self.prefetch_related("services", "services__options")

    def with_slug(self):
        return self.filter(slug__isnull=False).exclude(slug="")


class BundleQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def popular(self):
        return self.filter(is_popular=True)

    def with_items(self):
        return self.prefetch_related(
            "items", "items__option", "items__option__service"
        )

    def with_slug(self):
        return self.filter(slug__isnull=False).exclude(slug="")

    def ordered(self):
        # Bundle.Meta.ordering отсутствует — сортируем явно.
        return self.order_by("order", "name")


class PromotionQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def with_options(self):
        return self.prefetch_related("options", "options__service")

    def ordered(self):
        return self.order_by("order", "-starts_at", "title")


class ReviewQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def ordered(self):
        return self.order_by("order", "-date", "-created_at")
