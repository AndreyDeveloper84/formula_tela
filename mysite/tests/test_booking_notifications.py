"""Тесты email-уведомлений для wizard-заявок.

Покрывают:
- Парсинг SiteSettings.notification_emails → list[str]
- _send_booking_email: получатели из SiteSettings, fallback на ADMIN_NOTIFICATION_EMAIL
- api_wizard_booking вызывает _send_booking_email после создания BookingRequest
"""
import json
from unittest.mock import patch

import pytest
from model_bakery import baker

from services_app.models import BookingRequest, SiteSettings
from website.views import _send_booking_email


# ── SiteSettings.get_notification_emails ─────────────────────────────────────

@pytest.mark.django_db
def test_get_notification_emails_empty():
    site = baker.make(SiteSettings, notification_emails="")
    assert site.get_notification_emails() == []


@pytest.mark.django_db
def test_get_notification_emails_single_line():
    site = baker.make(SiteSettings, notification_emails="tikhonov-a-s@yandex.ru")
    assert site.get_notification_emails() == ["tikhonov-a-s@yandex.ru"]


@pytest.mark.django_db
def test_get_notification_emails_multiple_lines():
    site = baker.make(
        SiteSettings,
        notification_emails="admin@example.com\nmanager@example.com\n",
    )
    assert site.get_notification_emails() == [
        "admin@example.com",
        "manager@example.com",
    ]


@pytest.mark.django_db
def test_get_notification_emails_comma_separated():
    """Запятые тоже работают как разделитель."""
    site = baker.make(
        SiteSettings,
        notification_emails="a@example.com, b@example.com,c@example.com",
    )
    assert site.get_notification_emails() == [
        "a@example.com",
        "b@example.com",
        "c@example.com",
    ]


@pytest.mark.django_db
def test_get_notification_emails_skips_junk():
    """Пустые строки и строки без @ отбрасываются."""
    site = baker.make(
        SiteSettings,
        notification_emails="valid@example.com\n\nnot-an-email\n  \nalso@example.com",
    )
    assert site.get_notification_emails() == [
        "valid@example.com",
        "also@example.com",
    ]


# ── _send_booking_email ──────────────────────────────────────────────────────

@pytest.fixture
def booking(db):
    return baker.make(
        BookingRequest,
        category_name="Ручные массажи",
        service_name="Классический массаж",
        client_name="Алина",
        client_phone="+79991112233",
        comment="",
    )


@pytest.mark.django_db
def test_send_booking_email_uses_sitesettings(booking):
    baker.make(
        SiteSettings,
        notification_emails="tikhonov-a-s@yandex.ru\nmanager@example.com",
    )
    with patch("django.core.mail.send_mail") as mock_mail:
        _send_booking_email(booking)
    mock_mail.assert_called_once()
    assert mock_mail.call_args.kwargs["recipient_list"] == [
        "tikhonov-a-s@yandex.ru",
        "manager@example.com",
    ]
    assert "Классический массаж" in mock_mail.call_args.kwargs["subject"]
    assert "Алина" in mock_mail.call_args.kwargs["message"]


@pytest.mark.django_db
def test_send_booking_email_fallback_to_env(booking, settings):
    """Если SiteSettings пуст — берём ADMIN_NOTIFICATION_EMAIL."""
    settings.ADMIN_NOTIFICATION_EMAIL = "fallback@example.com"
    # SiteSettings.notification_emails пустой (или записи вообще нет)
    with patch("django.core.mail.send_mail") as mock_mail:
        _send_booking_email(booking)
    mock_mail.assert_called_once()
    assert mock_mail.call_args.kwargs["recipient_list"] == ["fallback@example.com"]


@pytest.mark.django_db
def test_send_booking_email_no_recipients_silent(booking, settings):
    """Пустой SiteSettings + пустой ADMIN_NOTIFICATION_EMAIL → ничего не шлём."""
    settings.ADMIN_NOTIFICATION_EMAIL = ""
    with patch("django.core.mail.send_mail") as mock_mail:
        _send_booking_email(booking)
    mock_mail.assert_not_called()


@pytest.mark.django_db
def test_send_booking_email_sitesettings_takes_priority(booking, settings):
    """SiteSettings перекрывает ADMIN_NOTIFICATION_EMAIL."""
    settings.ADMIN_NOTIFICATION_EMAIL = "env@example.com"
    baker.make(SiteSettings, notification_emails="admin@example.com")
    with patch("django.core.mail.send_mail") as mock_mail:
        _send_booking_email(booking)
    assert mock_mail.call_args.kwargs["recipient_list"] == ["admin@example.com"]


# ── api_wizard_booking интеграция ────────────────────────────────────────────

@pytest.mark.django_db
def test_wizard_booking_triggers_email(client, service, mock_telegram):
    baker.make(SiteSettings, notification_emails="tikhonov-a-s@yandex.ru")
    with patch("django.core.mail.send_mail") as mock_mail:
        resp = client.post(
            "/api/wizard/booking/",
            data=json.dumps({
                "client_name": "Алина",
                "client_phone": "+79991112233",
                "service_id": service.id,
            }),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    mock_mail.assert_called_once()
    assert "tikhonov-a-s@yandex.ru" in mock_mail.call_args.kwargs["recipient_list"]
    assert service.name in mock_mail.call_args.kwargs["subject"]
