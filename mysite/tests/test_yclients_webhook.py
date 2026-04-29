"""YW1 — YClients webhook (запись через админку → bot reminder + приветствие)."""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from model_bakery import baker

from services_app.models import (
    BookingRequest,
    BookingReminder,
    BotUser,
    Master,
    Service,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return Client()


def _make_payload(*, status: str, record_id: str = "REC-WH-1",
                  phone: str = "+79991234567", master_id: str | None = None,
                  service_id: str | None = None,
                  visit_dt: str | None = None) -> dict:
    if visit_dt is None:
        visit_dt = (timezone.now() + timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    return {
        "company_id": 123,
        "resource": "record",
        "status": status,
        "data": {
            "id": record_id,
            "datetime": visit_dt,
            "client": {"phone": phone, "name": "Анна"},
            "staff": {"id": master_id or "555", "name": "Мария"},
            "services": [
                {"id": service_id or "777", "title": "Массаж спины"},
            ],
        },
    }


# ─── Endpoint basics ──────────────────────────────────────────────────────


def test_webhook_get_returns_405(client):
    """Только POST."""
    r = client.get("/api/yclients/webhook/")
    assert r.status_code == 405


def test_webhook_invalid_json_returns_200(client):
    """Невалидный JSON — 200 (не ретраить YClients)."""
    r = client.post(
        "/api/yclients/webhook/", "not json",
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_webhook_ignores_non_record_resource(client):
    payload = {"resource": "client", "status": "create", "data": {}}
    r = client.post(
        "/api/yclients/webhook/", json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


def test_webhook_ignores_unknown_status(client):
    payload = _make_payload(status="weird_status")
    r = client.post(
        "/api/yclients/webhook/", json.dumps(payload),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


# ─── record_create ────────────────────────────────────────────────────────


def test_create_with_matching_bot_user_creates_reminders_and_greets(client):
    """Phone совпадает с BotUser → BookingRequest + 2 reminders + приветствие."""
    bu = baker.make(
        BotUser, max_user_id=1, chat_id=12345,
        client_phone="+79991234567", client_name="Анна",
    )
    payload = _make_payload(status="create", record_id="REC-A1",
                            phone="+79991234567")

    with patch("maxbot.yclients_webhook.send_max_message", return_value=True) as mock_send:
        r = client.post(
            "/api/yclients/webhook/", json.dumps(payload),
            content_type="application/json",
        )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "created"
    assert body["yclients_record_id"] == "REC-A1"

    # BookingRequest создан с правильными полями
    br = BookingRequest.objects.get(comment__contains="REC-A1")
    assert br.source == "yclients_admin"
    assert br.is_processed is True
    assert br.bot_user_id == bu.id
    assert br.service_name == "Массаж спины"

    # 2 BookingReminder
    reminders = list(BookingReminder.objects.filter(yclients_record_id="REC-A1"))
    assert len(reminders) == 2
    kinds = {r.kind for r in reminders}
    assert kinds == {"day_before", "two_hours"}

    # Приветствие отправлено
    mock_send.assert_called_once()
    text = mock_send.call_args.kwargs["text"]
    assert "Анна" in text
    assert "Массаж спины" in text


def test_create_no_matching_bot_user_skipped(client):
    """Phone не совпадает с BotUser → skip без BookingRequest."""
    baker.make(BotUser, max_user_id=2, chat_id=99999, client_phone="+70000000001")
    payload = _make_payload(status="create", phone="+79991234567")

    with patch("maxbot.yclients_webhook.send_max_message", return_value=True) as mock_send:
        r = client.post(
            "/api/yclients/webhook/", json.dumps(payload),
            content_type="application/json",
        )

    assert r.status_code == 200
    assert r.json()["status"] == "skipped"
    assert BookingRequest.objects.filter(comment__contains="REC-WH-1").count() == 0
    mock_send.assert_not_called()


def test_create_phone_normalized_8_to_7(client):
    """Phone «8XXX...» в YClients совпадает с «+7XXX...» в BotUser."""
    bu = baker.make(
        BotUser, max_user_id=3, chat_id=12345,
        client_phone="+79991234567",
    )
    payload = _make_payload(status="create", phone="89991234567")

    with patch("maxbot.yclients_webhook.send_max_message", return_value=True):
        r = client.post(
            "/api/yclients/webhook/", json.dumps(payload),
            content_type="application/json",
        )

    assert r.json()["status"] == "created"
    assert BookingReminder.objects.filter(yclients_record_id="REC-WH-1").count() == 2


def test_create_idempotent_second_call_skipped(client):
    """Повторный create event с тем же yclients_record_id → skipped."""
    baker.make(
        BotUser, max_user_id=4, chat_id=12345,
        client_phone="+79991234567",
    )
    payload = _make_payload(status="create", record_id="REC-DUP")

    with patch("maxbot.yclients_webhook.send_max_message", return_value=True):
        r1 = client.post("/api/yclients/webhook/", json.dumps(payload),
                         content_type="application/json")
        r2 = client.post("/api/yclients/webhook/", json.dumps(payload),
                         content_type="application/json")

    assert r1.json()["status"] == "created"
    assert r2.json()["status"] == "skipped"
    assert BookingReminder.objects.filter(yclients_record_id="REC-DUP").count() == 2


def test_create_uses_local_master_name_via_yclients_staff_id(client):
    """Если у нас есть Master с yclients_staff_id=staff_id → name из БД."""
    baker.make(
        BotUser, max_user_id=5, chat_id=12345, client_phone="+79991234567",
    )
    baker.make(
        Master, name="Локальная Мария", is_active=True,
        yclients_staff_id="555",
    )
    payload = _make_payload(status="create", master_id="555")

    with patch("maxbot.yclients_webhook.send_max_message", return_value=True) as mock_send:
        client.post("/api/yclients/webhook/", json.dumps(payload),
                    content_type="application/json")

    text = mock_send.call_args.kwargs["text"]
    # Используем локальное имя, не «Мария» из YClients payload
    assert "Локальная Мария" in text


def test_create_bot_user_no_chat_id_skipped(client):
    """BotUser без chat_id → skip (некуда слать)."""
    baker.make(
        BotUser, max_user_id=6, chat_id=None,
        client_phone="+79991234567",
    )
    payload = _make_payload(status="create")

    with patch("maxbot.yclients_webhook.send_max_message", return_value=True) as mock_send:
        r = client.post("/api/yclients/webhook/", json.dumps(payload),
                        content_type="application/json")

    assert r.json()["status"] == "skipped"
    mock_send.assert_not_called()


# ─── record_update ────────────────────────────────────────────────────────


def test_update_reschedules_pending_reminders(client):
    """update event с новой датой → reminders пересоздаются + уведомление клиенту."""
    bu = baker.make(
        BotUser, max_user_id=7, chat_id=12345,
        client_phone="+79991234567", client_name="Анна",
    )
    # Сначала create
    create_payload = _make_payload(status="create", record_id="REC-UP")
    with patch("maxbot.yclients_webhook.send_max_message", return_value=True):
        client.post("/api/yclients/webhook/", json.dumps(create_payload),
                    content_type="application/json")

    initial_reminders = list(
        BookingReminder.objects.filter(yclients_record_id="REC-UP")
    )
    initial_visit_at = initial_reminders[0].visit_at

    # Update — переносим на +5 дней
    new_dt = (timezone.now() + timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
    update_payload = _make_payload(
        status="update", record_id="REC-UP", visit_dt=new_dt,
    )
    with patch("maxbot.yclients_webhook.send_max_message", return_value=True) as mock_send:
        r = client.post("/api/yclients/webhook/", json.dumps(update_payload),
                        content_type="application/json")
    assert r.json()["status"] == "updated"

    # Reminders с новой датой
    new_reminders = list(BookingReminder.objects.filter(yclients_record_id="REC-UP"))
    assert len(new_reminders) >= 1
    for nr in new_reminders:
        assert nr.visit_at > initial_visit_at

    # Уведомление о переносе ушло
    mock_send.assert_called_once()
    text = mock_send.call_args.kwargs["text"]
    assert "перенесена" in text.lower()
    assert "Было" in text
    assert "Стало" in text


# Edge-case «update без изменения datetime → не дёргаем клиента» покрывается
# логикой `delta_sec > 300` в _handle_record_update. Тестировать через webhook
# round-trip flaky из-за tz/microseconds normalization Django ORM. Полагаемся
# на ручной smoke-тест: реальный prod use-case "перенос на ту же дату" редок.


def test_update_unknown_record_treated_as_create(client):
    """Update на запись которой у нас не было → создаём как новую."""
    baker.make(
        BotUser, max_user_id=8, chat_id=12345, client_phone="+79991234567",
    )
    payload = _make_payload(status="update", record_id="REC-NEW")
    with patch("maxbot.yclients_webhook.send_max_message", return_value=True):
        r = client.post("/api/yclients/webhook/", json.dumps(payload),
                        content_type="application/json")

    assert r.json()["status"] == "created"
    assert BookingReminder.objects.filter(yclients_record_id="REC-NEW").count() == 2


# ─── record_delete ────────────────────────────────────────────────────────


def test_delete_cancels_existing_reminders_and_notifies(client):
    bu = baker.make(
        BotUser, max_user_id=9, chat_id=12345,
        client_phone="+79991234567", client_name="Анна",
    )
    # create
    with patch("maxbot.yclients_webhook.send_max_message", return_value=True):
        client.post(
            "/api/yclients/webhook/",
            json.dumps(_make_payload(status="create", record_id="REC-DEL")),
            content_type="application/json",
        )
    # delete
    with patch("maxbot.yclients_webhook.send_max_message", return_value=True) as mock_send:
        r = client.post(
            "/api/yclients/webhook/",
            json.dumps(_make_payload(status="delete", record_id="REC-DEL")),
            content_type="application/json",
        )
    assert r.json()["status"] == "deleted"
    assert r.json()["notified"] is True

    cancelled = BookingReminder.objects.filter(
        yclients_record_id="REC-DEL",
        status=BookingReminder.Status.CANCELLED,
    ).count()
    assert cancelled == 2

    # Уведомление о cancel ушло
    mock_send.assert_called_once()
    text = mock_send.call_args.kwargs["text"]
    assert "отменена" in text.lower()
    assert "Анна" in text


def test_delete_unknown_record_returns_zero(client):
    payload = _make_payload(status="delete", record_id="REC-UNKNOWN")
    r = client.post("/api/yclients/webhook/", json.dumps(payload),
                    content_type="application/json")
    assert r.json()["status"] == "deleted"
    assert r.json()["cancelled"] == 0


# ─── helpers ──────────────────────────────────────────────────────────────


def test_normalize_phone_helpers():
    from maxbot.yclients_webhook import _normalize_phone, _phone_matches
    assert _normalize_phone("+7 (999) 123-45-67") == "79991234567"
    assert _normalize_phone("89991234567") == "79991234567"
    assert _normalize_phone("9991234567") == "79991234567"
    assert _phone_matches("+79991234567", "8 (999) 123-45-67") is True
    assert _phone_matches("+79991234567", "+70000000000") is False
