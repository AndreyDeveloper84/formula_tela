"""
URL configuration for mysite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse, JsonResponse

from agents.views import landing_page_view
from website.sitemaps import (
    BundleSitemap,
    CategorySitemap,
    LandingPageSitemap,
    ServiceSitemap,
    StaticViewSitemap,
)

sitemaps = {
    "static": StaticViewSitemap,
    "services": ServiceSitemap,
    "bundles": BundleSitemap,
    "categories": CategorySitemap,
    "landings": LandingPageSitemap,
}


def healthz(_request):
    return JsonResponse({"status": "ok"})


def robots_txt(_request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /admin/",
        "Disallow: /api/",
        "",
        f"Sitemap: {settings.SITE_BASE_URL}/sitemap.xml",
        f"Host: {settings.SITE_BASE_URL.replace('https://', '').replace('http://', '')}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


urlpatterns = [
    path('admin/', admin.site.urls),
    path('booking/', include('booking.urls')),  # Added trailing slash
    path('', include('website.urls')),
    path('healthz/', healthz, name='healthz'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap, {"sitemaps": sitemaps},
         name='django.contrib.sitemaps.views.sitemap'),

    # Посадочные страницы — слаг-маршрут должен быть последним,
    # чтобы не перехватывать admin/, booking/, healthz/ и т.д.
    path('<slug:slug>/', landing_page_view, name='landing_page'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)