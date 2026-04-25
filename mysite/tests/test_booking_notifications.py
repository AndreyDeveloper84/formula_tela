"""Тесты централизованных уведомлений — пакет `notifications/`.

Покрывают:
- SiteSettings.get_notification_emails() — парсинг поля
- notifications.send_notification_email — получатели из SiteSettings,
  fallback на ADMIN_NOTIFICATION_EMAIL, пустой список → no-op
- notifications.send_notification_telegram — без токенов no-op
- api_wizard_booking / api_bundle_request / api_certificate_request — все три
  endpoint'а вызывают helpers и шлют email на список из SiteSettings
"""
import json
from decimal import Decimal
from unittest.mock import patch

import pytest
from model_bakery import baker

from services_app.models import BookingRequest, SiteSettings
from notifications import (
    get_notification_recipients,
    send_notification_email,
    send_notification_telegram,
)


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


# ── notifications.get_notification_recipients ──────────────────────────────

@pytest.mark.django_db
def test_recipients_from_sitesettings_when_present():
    baker.make(SiteSettings, notification_emails="a@example.com\nb@example.com")
    assert get_notification_recipients() == ["a@example.com", "b@example.com"]


@pytest.mark.django_db
def test_recipients_fallback_to_env_when_sitesettings_empty(settings):
    settings.ADMIN_NOTIFICATION_EMAIL = "env-admin@example.com"
    assert get_notification_recipients() == ["env-admin@example.com"]


@pytest.mark.django_db
def test_recipients_empty_when_all_empty(settings):
    settings.ADMIN_NOTIFICATION_EMAIL = ""
    assert get_notification_recipients() == []


@pytest.mark.django_db
def test_recipients_sitesettings_priority_over_env(settings):
    settings.ADMIN_NOTIFICATION_EMAIL = "env@example.com"
    baker.make(SiteSettings, notification_emails="admin@example.com")
    assert get_notification_recipients() == ["admin@example.com"]


# ── notifications.send_notification_email ──────────────────────────────────

@pytest.mark.django_db
def test_send_notification_email_uses_sitesettings():
    baker.make(SiteSettings, notification_emails="a@example.com\nb@example.com")
    with patch("notifications.send_mail") as mock_mail:
        result = send_notification_email("Тема", "Тело")
    assert result is True
    mock_mail.assert_called_once()
    assert mock_mail.call_args.kwargs["recipient_list"] == ["a@example.com", "b@example.com"]
    assert mock_mail.call_args.kwargs["subject"] == "Тема"
    assert mock_mail.call_args.kwargs["message"] == "Тело"


@pytest.mark.django_db
def test_send_notification_email_no_recipients_silent(settings):
    settings.ADMIN_NOTIFICATION_EMAIL = ""
    with patch("notifications.send_mail") as mock_mail:
        result = send_notification_email("Тема", "Тело")
    assert result is False
    mock_mail.assert_not_called()


# ── notifications.send_notification_telegram ───────────────────────────────

def test_send_notification_telegram_no_token_silent(settings):
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.TELEGRAM_CHAT_ID = ""
    with patch("notifications.http_requests.post") as mock_post:
        result = send_notification_telegram("Тест")
    assert result is False
    mock_post.assert_not_called()


def test_send_notification_telegram_sends_when_configured(settings):
    settings.TELEGRAM_BOT_TOKEN = "fake-token"
    settings.TELEGRAM_CHAT_ID = "fake-chat"
    with patch("notifications.http_requests.post") as mock_post:
        mock_post.return_value.ok = True
        result = send_notification_telegram("Тест-сообщение")
    assert result is True
    mock_post.assert_called_once()
    url_arg = mock_post.call_args[0][0]
    assert "fake-token" in url_arg
    assert mock_post.call_args.kwargs["json"]["chat_id"] == "fake-chat"
    assert mock_post.call_args.kwargs["json"]["text"] == "Тест-сообщение"


# ── Hot fix: proxy для api.telegram.org (заблокирован в РФ) ──────────────────

def test_send_notification_telegram_uses_telegram_proxy(settings):
    """TELEGRAM_PROXY → передаётся в proxies={'https': ...}."""
    settings.TELEGRAM_BOT_TOKEN = "tok"
    settings.TELEGRAM_CHAT_ID = "ch"
    settings.TELEGRAM_PROXY = "http://user:pass@proxy.example:3128"
    settings.OPENAI_PROXY = ""
    with patch("notifications.http_requests.post") as mock_post:
        mock_post.return_value.ok = True
        send_notification_telegram("X")
    assert mock_post.call_args.kwargs["proxies"] == {"https": "http://user:pass@proxy.example:3128"}


def test_send_notification_telegram_falls_back_to_openai_proxy(settings):
    """OPENAI_PROXY как fallback если TELEGRAM_PROXY пуст."""
    settings.TELEGRAM_BOT_TOKEN = "tok"
    settings.TELEGRAM_CHAT_ID = "ch"
    settings.TELEGRAM_PROXY = ""
    settings.OPENAI_PROXY = "http://openai-proxy:8080"
    with patch("notifications.http_requests.post") as mock_post:
        mock_post.return_value.ok = True
        send_notification_telegram("X")
    assert mock_post.call_args.kwargs["proxies"] == {"https": "http://openai-proxy:8080"}


def test_send_notification_telegram_no_proxies_when_none_set(settings):
    settings.TELEGRAM_BOT_TOKEN = "tok"
    settings.TELEGRAM_CHAT_ID = "ch"
    settings.TELEGRAM_PROXY = ""
    settings.OPENAI_PROXY = ""
    with patch("notifications.http_requests.post") as mock_post:
        mock_post.return_value.ok = True
        send_notification_telegram("X")
    assert mock_post.call_args.kwargs["proxies"] is None


def test_send_notification_telegram_returns_false_on_http_error(settings):
    """Если Telegram вернул не-2xx — возвращаем False (раньше всегда True)."""
    settings.TELEGRAM_BOT_TOKEN = "tok"
    settings.TELEGRAM_CHAT_ID = "ch"
    with patch("notifications.http_requests.post") as mock_post:
        mock_post.return_value.ok = False
        mock_post.return_value.status_code = 400
        mock_post.return_value.text = "bad request"
        assert send_notification_telegram("X") is False


# ── api_wizard_booking — интеграция ─────────────────────────────────────────

@pytest.mark.django_db
def test_wizard_booking_triggers_notification(client, service, mock_telegram):
    baker.make(SiteSettings, notification_emails="tikhonov-a-s@yandex.ru")
    with patch("notifications.send_mail") as mock_mail:
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
    assert BookingRequest.objects.filter(service_name=service.name).exists()


@pytest.mark.django_db
def test_wizard_booking_saves_master_name(client, service, mock_telegram):
    """Покупатель нажал «Записаться» в карточке мастера → master_name
    доходит до BookingRequest и упоминается в уведомлениях."""
    baker.make(SiteSettings, notification_emails="manager@example.com")
    with patch("notifications.send_mail") as mock_mail:
        resp = client.post(
            "/api/wizard/booking/",
            data=json.dumps({
                "client_name": "Андрей",
                "client_phone": "+79990001122",
                "service_id": service.id,
                "master_name": "Елена Миронова",
            }),
            content_type="application/json",
        )
    assert resp.status_code == 200
    booking = BookingRequest.objects.get(service_name=service.name)
    assert booking.master_name == "Елена Миронова"
    # Master name is in the email body
    body = mock_mail.call_args.kwargs["message"]
    assert "Елена Миронова" in body


# ── api_bundle_request — интеграция ─────────────────────────────────────────

@pytest.mark.django_db
def test_bundle_request_triggers_notification(client, bundle, mock_telegram):
    baker.make(SiteSettings, notification_emails="manager@example.com")
    with patch("notifications.send_mail") as mock_mail:
        resp = client.post(
            "/api/bundle/request/",
            data=json.dumps({
                "name": "Иван",
                "phone": "+79001234567",
                "bundle_id": bundle.id,
                "bundle_name": bundle.name,
                "comment": "",
            }),
            content_type="application/json",
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    mock_mail.assert_called_once()
    assert mock_mail.call_args.kwargs["recipient_list"] == ["manager@example.com"]
    assert bundle.name in mock_mail.call_args.kwargs["subject"]


# ── api_certificate_request — интеграция ───────────────────────────────────

@pytest.mark.django_db
def test_certificate_request_triggers_notification(client, mock_telegram):
    baker.make(SiteSettings, notification_emails="certificates@example.com")
    with patch("notifications.send_mail") as mock_mail:
        resp = client.post(
            "/api/certificates/request/",
            data=json.dumps({
                "certificate_type": "nominal",
                "nominal": 3000,
                "buyer_name": "Тест",
                "buyer_phone": "+79990001122",
            }),
            content_type="application/json",
        )
    assert resp.status_code == 200
    mock_mail.assert_called_once()
    assert mock_mail.call_args.kwargs["recipient_list"] == ["certificates@example.com"]
    assert "сертификат" in mock_mail.call_args.kwargs["subject"].lower()
