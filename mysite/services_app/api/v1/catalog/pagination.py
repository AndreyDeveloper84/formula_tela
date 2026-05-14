"""Cursor pagination ordered by ``updated_at``.

DRF's :class:`rest_framework.pagination.CursorPagination` uses a stable
cursor over an *ordered* field. Ordering by ``updated_at`` is the right
choice for an incremental sync API: new rows always appear at the tail,
so a paginating consumer never accidentally skips or duplicates a row
even when the dataset is changing during the sync.

Page size: 200. Tuned for the bot's sync cycle — large enough that a
typical formulatela catalog (~40 services, ~10 masters, dozens of FAQs)
fits in a single page; small enough that even a 10K-row growth doesn't
exhaust per-request CPU.
"""
from __future__ import annotations

from rest_framework.pagination import CursorPagination


class CatalogCursorPagination(CursorPagination):
    """Stable cursor pagination on ``updated_at``."""

    page_size = 200
    ordering = "updated_at"
    cursor_query_param = "cursor"
