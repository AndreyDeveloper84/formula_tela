import datetime

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from agents.models import LandingPage
from services_app.models import Bundle, Service, ServiceCategory


class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = "weekly"

    def items(self):
        return ["website:home", "website:services", "website:promotions",
                "website:masters", "website:contacts", "website:bundles",
                "website:certificates"]

    def location(self, item):
        return reverse(item)


class ServiceSitemap(Sitemap):
    priority = 0.9
    changefreq = "weekly"

    def items(self):
        return Service.objects.filter(is_active=True, slug__isnull=False).exclude(slug="").order_by("slug")

    def location(self, obj):
        return reverse("website:service_detail_by_slug", kwargs={"slug": obj.slug})

    def lastmod(self, obj):
        return obj.updated_at


class BundleSitemap(Sitemap):
    priority = 0.7
    changefreq = "monthly"

    def items(self):
        return Bundle.objects.filter(is_active=True, slug__isnull=False).exclude(slug="").order_by("slug")

    def location(self, obj):
        return reverse("website:bundle_detail_by_slug", kwargs={"slug": obj.slug})


class CategorySitemap(Sitemap):
    """
    Категории доступны только по числовым ID (/services/<id>/) — без slug.
    Такие URL не имеют SEO-ценности и зря расходуют краулинг-бюджет.
    items() возвращает пустой список пока у категорий не появятся slug-based URL.
    """
    priority = 0.7
    changefreq = "weekly"

    def items(self):
        return []

    def location(self, obj):
        return reverse("website:category_services", kwargs={"category_id": obj.pk})


class LandingPageSitemap(Sitemap):
    priority = 0.8
    changefreq = "monthly"

    def items(self):
        return LandingPage.objects.filter(status=LandingPage.STATUS_PUBLISHED).order_by("slug")

    def location(self, obj):
        return reverse("landing_page", kwargs={"slug": obj.slug})

    def lastmod(self, obj):
        return obj.published_at
