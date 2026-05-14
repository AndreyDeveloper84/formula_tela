"""``?since=<ISO8601>`` query-string filter — incremental sync cursor.

When the bot syncs the catalog it stores the last seen ``updated_at``
and on the next cycle passes it back as ``?since=...``. The endpoint
returns only rows mutated since that timestamp. Combined with cursor
pagination (ordered by ``updated_at``) this gives the bot an
**incremental sync stream** without ever pulling the full table after
the initial bootstrap.

Implementation note: we accept any ISO-8601 string Django's
:func:`django.utils.dateparse.parse_datetime` understands. Invalid
input is silently ignored (no filter applied) rather than 400'd because
the M1 contract is read-only and an invalid cursor is a consumer bug,
not a security issue — we'd rather serve a slightly larger page than
break a sync cycle on a typo.
"""
from __future__ import annotations

from django.utils.dateparse import parse_datetime
from rest_framework.filters import BaseFilterBackend
from rest_framework.request import Request


class SinceUpdatedAtFilter(BaseFilterBackend):
    """Filter the queryset to rows where ``updated_at > since``."""

    def filter_queryset(self, request: Request, queryset, view):  # type: ignore[no-untyped-def]
        raw = request.query_params.get("since")
        if not raw:
            return queryset
        parsed = parse_datetime(raw)
        if parsed is None:
            # Invalid ISO-8601 — silently skip the filter (see module docstring).
            return queryset
        return queryset.filter(updated_at__gt=parsed)
