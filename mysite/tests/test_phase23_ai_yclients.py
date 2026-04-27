"""Phase 2.3 post-T11: enrich_show_slots + enrich_show_my_bookings."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

pytestmark = pytest.mark.django_db(transaction=True)


# ─── enrich_show_slots ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_slots_happy_path_fetches_yclients():
    from maxbot.ai_yclients import enrich_show_slots
    from services_app.models import Master, Service, ServiceOption

    master = await sync_to_async(baker.make)(
        Master, name="Анна", is_active=True, yclients_staff_id="111",
    )
    service = await sync_to_async(baker.make)(Service, name="Массаж", is_active=True)
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="222", is_active=True,
    )

    api = MagicMock()
    api.get_available_times = MagicMock(return_value=["10:00", "11:30", "14:00"])

    data = {"master_id": master.id, "service_id": service.id, "date": "2026-04-30"}
    result = await enrich_show_slots(data, yclients_api=api)

    assert result["master_name"] == "Анна"
    assert result["service_name"] == "Массаж"
    assert result["slots"] == ["10:00", "11:30", "14:00"]

    # YClients API вызвана с правильными int IDs из mapping
    api.get_available_times.assert_called_once_with(
        staff_id=111, date="2026-04-30", service_ids=[222],
    )


@pytest.mark.asyncio
async def test_enrich_slots_no_master_yclients_mapping_returns_empty():
    """Master без yclients_staff_id → empty slots, YClients API не зовётся."""
    from maxbot.ai_yclients import enrich_show_slots
    from services_app.models import Master, Service, ServiceOption

    master = await sync_to_async(baker.make)(
        Master, name="Без mapping", is_active=True, yclients_staff_id="",
    )
    service = await sync_to_async(baker.make)(Service, name="Массаж", is_active=True)
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="222", is_active=True,
    )
    api = MagicMock()

    data = {"master_id": master.id, "service_id": service.id, "date": "2026-04-30"}
    result = await enrich_show_slots(data, yclients_api=api)

    assert result["slots"] == []
    api.get_available_times.assert_not_called()
    # Имена всё равно подгружены — рендер «Анна — Массаж: слотов нет»
    assert result["master_name"] == "Без mapping"
    assert result["service_name"] == "Массаж"


@pytest.mark.asyncio
async def test_enrich_slots_no_service_option_returns_empty():
    """Service без ServiceOption.yclients_service_id → empty slots."""
    from maxbot.ai_yclients import enrich_show_slots
    from services_app.models import Master, Service

    master = await sync_to_async(baker.make)(
        Master, is_active=True, yclients_staff_id="111",
    )
    service = await sync_to_async(baker.make)(Service, is_active=True)
    # Намеренно НЕ создаём ServiceOption
    api = MagicMock()

    data = {"master_id": master.id, "service_id": service.id, "date": "2026-04-30"}
    result = await enrich_show_slots(data, yclients_api=api)
    assert result["slots"] == []
    api.get_available_times.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_slots_yclients_failure_returns_empty():
    from maxbot.ai_yclients import enrich_show_slots
    from services_app.models import Master, Service, ServiceOption

    master = await sync_to_async(baker.make)(
        Master, is_active=True, yclients_staff_id="111",
    )
    service = await sync_to_async(baker.make)(Service, is_active=True)
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="222", is_active=True,
    )
    api = MagicMock()
    api.get_available_times = MagicMock(side_effect=RuntimeError("YClients 503"))

    data = {"master_id": master.id, "service_id": service.id, "date": "2026-04-30"}
    result = await enrich_show_slots(data, yclients_api=api)
    assert result["slots"] == []  # graceful, render покажет «нет слотов»


@pytest.mark.asyncio
async def test_enrich_slots_truncates_to_12():
    from maxbot.ai_yclients import enrich_show_slots
    from services_app.models import Master, Service, ServiceOption

    master = await sync_to_async(baker.make)(
        Master, is_active=True, yclients_staff_id="111",
    )
    service = await sync_to_async(baker.make)(Service, is_active=True)
    await sync_to_async(baker.make)(
        ServiceOption, service=service, yclients_service_id="222", is_active=True,
    )
    api = MagicMock()
    api.get_available_times = MagicMock(
        return_value=[f"{h:02d}:00" for h in range(8, 22)]  # 14 slots
    )

    data = {"master_id": master.id, "service_id": service.id, "date": "2026-04-30"}
    result = await enrich_show_slots(data, yclients_api=api)
    assert len(result["slots"]) == 12


@pytest.mark.asyncio
async def test_enrich_slots_invalid_master_id_returns_empty():
    from maxbot.ai_yclients import enrich_show_slots

    api = MagicMock()
    data = {"master_id": 99999, "service_id": 99999, "date": "2026-04-30"}
    result = await enrich_show_slots(data, yclients_api=api)
    assert result["slots"] == []
    assert result["master_name"] == "—"
    assert result["service_name"] == "—"


# ─── enrich_show_my_bookings ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enrich_bookings_no_phone_returns_empty():
    from maxbot.ai_yclients import enrich_show_my_bookings
    from services_app.models import BotUser

    bu = await sync_to_async(baker.make)(BotUser, max_user_id=99001, client_phone="")
    api = MagicMock()

    data = {"filter": "upcoming"}
    result = await enrich_show_my_bookings(data, bu, yclients_api=api)
    assert result["bookings"] == []
    api.get_records.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_bookings_yclients_failure_returns_empty():
    from maxbot.ai_yclients import enrich_show_my_bookings
    from services_app.models import BotUser

    bu = await sync_to_async(baker.make)(
        BotUser, max_user_id=99002, client_phone="+79991234567",
    )
    api = MagicMock()
    api.get_records = MagicMock(side_effect=RuntimeError("YClients 503"))

    data = {"filter": "upcoming"}
    result = await enrich_show_my_bookings(data, bu, yclients_api=api)
    assert result["bookings"] == []


@pytest.mark.asyncio
async def test_enrich_bookings_maps_yclients_response():
    from maxbot.ai_yclients import enrich_show_my_bookings
    from services_app.models import BotUser

    bu = await sync_to_async(baker.make)(
        BotUser, max_user_id=99003, client_phone="+79991234567",
    )
    api = MagicMock()
    api.get_records = MagicMock(return_value=[
        {
            "datetime": "2099-12-31T14:00:00+03:00",  # future → upcoming
            "services": [{"title": "Массаж спины"}],
            "staff": {"name": "Анна"},
        },
    ])

    data = {"filter": "upcoming"}
    result = await enrich_show_my_bookings(data, bu, yclients_api=api)
    assert len(result["bookings"]) == 1
    b = result["bookings"][0]
    assert b["master_name"] == "Анна"
    assert b["service_name"] == "Массаж спины"
    assert "2099" in b["datetime"]
