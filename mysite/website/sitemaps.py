import datetime

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from agents.models import LandingPage
from services_app.models import Bundle, Master, Service, ServiceCategory


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

    # NB: lastmod removed — у Service нет полей created_at/updated_at в БД,
    # а добавление их через миграцию + auto_now выходит за рамки hotfix'а.
    # Если SEO потребуется lastmod — добавить отдельным коммитом:
    #   1) AddField Service.updated_at + created_at (auto_now / auto_now_add)
    #   2) Вернуть метод lastmod(self, obj): return obj.updated_at


class BundleSitemap(Sitemap):
    priority = 0.7
    changefreq = "monthly"

    def items(self):
        return Bundle.objects.filter(is_active=True, slug__isnull=False).exclude(slug="").order_by("slug")

    def location(self, obj):
        return reverse("website:bundle_detail_by_slug", kwargs={"slug": obj.slug})


class MasterSitemap(Sitemap):
    priority = 0.8
    changefreq = "monthly"

    def items(self):
        return (Master.objects
                .filter(is_active=True, slug__isnull=False)
                .exclude(slug="")
                .order_by("slug"))

    def location(self, obj):
        return reverse("website:master_detail_by_slug", kwargs={"slug": obj.slug})


class CategorySitemap(Sitemap):
    priority = 0.7
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
    """
    Landing-страницы временно закрыты от индексации.

    Причина: агенты SEOLanding Agent генерируют лендинги автоматически,
    но качество генерации пока не отслеживается — есть дубли H1, устаревшие
    ссылки, пересечения с /uslugi/<slug>/. Пока не настроен агент,
    отслеживающий качество, их не стоит отдавать в Яндекс/Google.

    items() возвращает пустой список → в sitemap.xml ничего не попадает.
    Плюс на самой странице (templates/agents/landing_page.html) стоит
    <meta name="robots" content="noindex, nofollow">.

    Когда SEO-агент будет готов — вернуть items() + lastmod() и убрать
    noindex из шаблона.
    """
    priority = 0.8
    changefreq = "monthly"

    def items(self):
        return []

    def location(self, obj):
        return reverse("landing_page", kwargs={"slug": obj.slug})
