from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from agents.models import LandingPage
from services_app.models import Service, ServiceCategory


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


class CategorySitemap(Sitemap):
    priority = 0.7
    changefreq = "weekly"

    def items(self):
        return ServiceCategory.objects.all().order_by("pk")

    def location(self, obj):
        return reverse("website:category_services", kwargs={"category_id": obj.pk})


class LandingPageSitemap(Sitemap):
    priority = 0.8
    changefreq = "monthly"

    def items(self):
        return LandingPage.objects.filter(status=LandingPage.STATUS_PUBLISHED).order_by("slug")

    def location(self, obj):
        return reverse("landing_page", kwargs={"slug": obj.slug})
