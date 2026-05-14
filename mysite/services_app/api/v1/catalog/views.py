"""Read-only DRF viewsets for the catalog endpoints.

Each viewset is a :class:`~rest_framework.viewsets.ReadOnlyModelViewSet`
(``GET`` list + ``GET`` retrieve only — no write endpoints). Catalog
editing happens through the Django admin, never the API; exposing
write endpoints would create a cross-system source-of-truth conflict
that's painful to undo.

The four resources share:

- **Queryset**: ``is_active=True`` for Service / Master / HelpArticle
  (FAQ has no ``is_active`` filter applied because the bot needs to
  see *all* FAQs and decide context-by-context which to surface).
  - Actually FAQ does have ``is_active`` — we filter it the same way
    for consistency.
- **Filter**: :class:`SinceUpdatedAtFilter` — ``?since=<ISO8601>``.
- **Pagination**: :class:`CatalogCursorPagination` — cursor over
  ``updated_at``.

We order by ``updated_at`` ascending to match the cursor's expectation
and to give the bot rows in chronological mutation order.
"""
from __future__ import annotations

from rest_framework.viewsets import ReadOnlyModelViewSet

from services_app.models import FAQ, HelpArticle, Master, Service

from .filters import SinceUpdatedAtFilter
from .pagination import CatalogCursorPagination
from .serializers import (
    FAQSerializer,
    HelpArticleSerializer,
    MasterSerializer,
    ServiceSerializer,
)


class _CatalogBaseViewSet(ReadOnlyModelViewSet):
    """Shared configuration for every catalog viewset.

    Subclasses set ``queryset`` and ``serializer_class``; everything
    else (filter + pagination + ordering) is inherited unchanged.
    """

    pagination_class = CatalogCursorPagination
    filter_backends = [SinceUpdatedAtFilter]


class ServiceViewSet(_CatalogBaseViewSet):
    """``GET /api/v1/catalog/services/`` — active services."""

    queryset = (
        Service.objects.filter(is_active=True)
        .select_related("category")
        .order_by("updated_at")
    )
    serializer_class = ServiceSerializer


class MasterViewSet(_CatalogBaseViewSet):
    """``GET /api/v1/catalog/masters/`` — active masters with services list."""

    queryset = (
        Master.objects.filter(is_active=True)
        .prefetch_related("services")
        .order_by("updated_at")
    )
    serializer_class = MasterSerializer


class FaqViewSet(_CatalogBaseViewSet):
    """``GET /api/v1/catalog/faqs/`` — active service-category FAQs."""

    queryset = (
        FAQ.objects.filter(is_active=True)
        .select_related("category")
        .order_by("updated_at")
    )
    serializer_class = FAQSerializer


class HelpArticleViewSet(_CatalogBaseViewSet):
    """``GET /api/v1/catalog/help-articles/`` — active MAX-bot help articles."""

    queryset = (
        HelpArticle.objects.filter(is_active=True)
        .order_by("updated_at")
    )
    serializer_class = HelpArticleSerializer
