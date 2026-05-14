"""DRF serializers — flat shapes free of FK objects.

The bot's sync layer mirrors these rows into ai-bot-platform's
``apps.catalog.*`` tables, so we expose **scalar fields only** and
substitute related FK / M2M objects with their human-readable names
(or PKs where the bot needs to map between systems, e.g.
``yclients_staff_id`` on Master).

Each serializer follows the same field shape:

- ``id``           — primary key (used by the bot's mirror as
  ``external_id``)
- ``updated_at``   — sync cursor; also used to order cursor pagination
- business fields — the actual content the bot grounds answers on

No ``created_at`` or audit fields are exposed — those are bookkeeping
state of the mysite side, not data the bot needs.
"""
from __future__ import annotations

from rest_framework import serializers

from services_app.models import FAQ, HelpArticle, Master, Service


class ServiceSerializer(serializers.ModelSerializer):
    """Flat service shape for the bot's catalog mirror.

    ``category_name`` is a string (not the FK object) because the bot's
    own ``apps.catalog.Service`` mirror keeps the category as a string
    label, not a relation; it doesn't need to navigate categories.
    """

    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = Service
        fields = [
            "id",
            "updated_at",
            "name",
            "short",
            "description",
            "duration_min",
            "price_from",
            "is_active",
            "is_popular",
            "category_name",
        ]


class MasterSerializer(serializers.ModelSerializer):
    """Flat master shape with ``services`` as a list of service PKs.

    The bot uses this list to validate ``(master_id, service_id)`` pairs
    in :func:`ayla_ai_core.tool_handlers.handle_show_slots` — i.e. the
    anti-hallucination cross-check that the master actually offers the
    chosen service.

    ``yclients_staff_id`` is exposed so the bot can later map a master
    to the YClients staff id for native-booking integration (Phase 2.3).
    """

    services = serializers.PrimaryKeyRelatedField(
        many=True,
        read_only=True,
    )

    class Meta:
        model = Master
        fields = [
            "id",
            "updated_at",
            "name",
            "slug",
            "specialization",
            "bio",
            "experience",
            "yclients_staff_id",
            "is_active",
            "services",
        ]


class FAQSerializer(serializers.ModelSerializer):
    """Flat FAQ shape for service-category FAQ items."""

    category_name = serializers.CharField(
        source="category.name",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = FAQ
        fields = [
            "id",
            "updated_at",
            "question",
            "answer",
            "order",
            "category_name",
            "is_active",
        ]


class HelpArticleSerializer(serializers.ModelSerializer):
    """Flat help-article shape for the MAX-bot FAQ store.

    These are the rows the bot historically grounded answers on in its
    original ``legacy_formulatela_mcp/`` chromadb collection.
    """

    class Meta:
        model = HelpArticle
        fields = [
            "id",
            "updated_at",
            "question",
            "answer",
            "order",
            "is_active",
        ]
