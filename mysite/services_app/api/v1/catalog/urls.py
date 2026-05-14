"""URL routing — ``/api/v1/catalog/{services,masters,faqs,help-articles}/``.

We use DRF's :class:`~rest_framework.routers.DefaultRouter` so each
viewset gets the standard list + retrieve URL pair without manual
``path()`` declarations.

Plural / hyphenated URL fragments are wire-format **stable** — the bot
pins these strings. Any rename here is a v2 endpoint, not a v1 patch.
"""
from __future__ import annotations

from rest_framework.routers import DefaultRouter

from .views import FaqViewSet, HelpArticleViewSet, MasterViewSet, ServiceViewSet

router = DefaultRouter()
router.register(r"services", ServiceViewSet, basename="catalog-service")
router.register(r"masters", MasterViewSet, basename="catalog-master")
router.register(r"faqs", FaqViewSet, basename="catalog-faq")
router.register(r"help-articles", HelpArticleViewSet, basename="catalog-help-article")

urlpatterns = router.urls
