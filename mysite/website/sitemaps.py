import datetime

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from agents.models import LandingPage
from services_app.models import Bundle, Master, Service, ServiceCategory


class StaticViewSitemap(Sitemap):
    changefreq = "weekly"

    _priorities = {
        "website:home": 1.0,
        "website:services": 0.9,
        "website:masters": 0.7,
        "website:promotions": 0.6,
        "website:contacts": 0.6,
        "website:bundles": 0.6,
        "website:certificates": 0.6,
    }

    def items(self):
        return ["website:home", "website:services", "website:promotions",
                "website:masters", "website:contacts", "website:bundles",
                "website:certificates"]

    def location(self, item):
        return reverse(item)

    def priority(self, item):
        return self._priorities.get(item, 0.5)


class ServiceSitemap(Sitemap):
    priority = 0.9
    changefreq = "weekly"

    def items(self):
        return Service.objects.active().with_slug().order_by("slug")

    def location(self, obj):
        return reverse("website:service_detail_by_slug", kwargs={"slug": obj.slug})

    def lastmod(self, obj):
        return obj.updated_at


class BundleSitemap(Sitemap):
    priority = 0.7
    changefreq = "monthly"

    def items(self):
        return Bundle.objects.active().with_slug().order_by("slug")

    def location(self, obj):
        return reverse("website:bundle_detail_by_slug", kwargs={"slug": obj.slug})

    def lastmod(self, obj):
        return obj.updated_at


class MasterSitemap(Sitemap):
    priority = 0.7
    changefreq = "monthly"

    def items(self):
        return Master.objects.active().with_slug().order_by("slug")

    def location(self, obj):
        return reverse("website:master_detail_by_slug", kwargs={"slug": obj.slug})


class CategorySitemap(Sitemap):
    priority = 0.8
    changefreq = "weekly"

    def items(self):
        return (
            ServiceCategory.objects
            .filter(slug__isnull=False)
            .exclude(slug="")
            .order_by("slug")
        )

    def location(self, obj):
        return reverse("website:category_services_by_slug", kwargs={"slug": obj.slug})


class LandingPageSitemap(Sitemap):
    """Landing-страницы, прошедшие QC-проверку (SEOLandingQCAgent).

    Только published + с заполненным published_at попадают в sitemap.
    QC-агент проверяет H1/slug уникальность, наличие блоков, дубли контента
    и устанавливает published_at при переводе в published.
    """
    priority = 0.8
    changefreq = "monthly"

    def items(self):
        return (
            LandingPage.objects.published()
            .filter(published_at__isnull=False)
            .order_by("slug")
        )

    def location(self, obj):
        return reverse("landing_page", kwargs={"slug": obj.slug})

    def lastmod(self, obj):
        return obj.published_at
