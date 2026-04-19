"""
Тесты для генерации PDF-сертификатов и email с вложением.
"""
import json
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from model_bakery import baker


# ── generate_certificate_pdf ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestGenerateCertificatePdf:
    def _make_cert(self, cert_type="nominal", **kwargs):
        order = baker.make(
            "services_app.Order",
            order_type="certificate",
            client_name="Тест",
            client_phone="+79990001122",
            total_amount=Decimal("3000"),
        )
        today = date.today()
        return baker.make(
            "services_app.GiftCertificate",
            order=order,
            certificate_type=cert_type,
            nominal=Decimal("3000"),
            buyer_name="Тест",
            buyer_phone="+79990001122",
            valid_from=today,
            valid_until=today + timedelta(days=180),
            status="paid",
            **kwargs,
        ), order

    def test_returns_bytes_nominal(self):
        import sys
        fake_wp = MagicMock()
        fake_wp.HTML.return_value.write_pdf.return_value = b"%PDF-nominal"
        sys.modules["weasyprint"] = fake_wp

        import payments.certificate_pdf as mod
        cert, order = self._make_cert("nominal")
        result = mod.generate_certificate_pdf(cert, order)
        assert result == b"%PDF-nominal"
        fake_wp.HTML.assert_called_once()

    def test_returns_bytes_bundle_type(self):
        import sys
        fake_wp = MagicMock()
        fake_wp.HTML.return_value.write_pdf.return_value = b"%PDF-bundle"
        sys.modules["weasyprint"] = fake_wp

        bundle = baker.make(
            "services_app.Bundle",
            name="SPA Комплекс",
            is_active=True,
            is_certificate=True,
            certificate_theme="dark",
        )
        cert, order = self._make_cert("bundle", bundle=bundle)

        import payments.certificate_pdf as mod
        result = mod.generate_certificate_pdf(cert, order)
        assert result == b"%PDF-bundle"

    def test_raises_if_weasyprint_unavailable(self):
        import sys
        import builtins

        if "weasyprint" in sys.modules:
            del sys.modules["weasyprint"]

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "weasyprint":
                raise ImportError("weasyprint not installed")
            return real_import(name, *args, **kwargs)

        builtins.__import__ = mock_import
        try:
            import payments.certificate_pdf as mod
            cert, order = self._make_cert("nominal")
            with pytest.raises(ImportError):
                mod.generate_certificate_pdf(cert, order)
        finally:
            builtins.__import__ = real_import


# ── send_certificate_email ───────────────────────────────────────────────────


@pytest.mark.django_db
class TestSendCertificateEmail:
    def _make_order_cert(self, email="buyer@example.com", cert_type="nominal"):
        order = baker.make(
            "services_app.Order",
            order_type="certificate",
            client_name="Покупатель",
            client_phone="+79990001122",
            client_email=email,
            total_amount=Decimal("3000"),
        )
        today = date.today()
        cert = baker.make(
            "services_app.GiftCertificate",
            order=order,
            certificate_type=cert_type,
            nominal=Decimal("3000"),
            buyer_name="Покупатель",
            buyer_phone="+79990001122",
            buyer_email=email,
            valid_from=today,
            valid_until=today + timedelta(days=180),
            status="paid",
        )
        return order, cert

    def test_sends_email_without_pdf(self, monkeypatch):
        from unittest.mock import MagicMock
        mock_send = MagicMock()
        monkeypatch.setattr("website.notifications.EmailMessage", mock_send)

        from website.notifications import send_certificate_email
        order, cert = self._make_order_cert()
        result = send_certificate_email(order, cert)
        assert result is True
        instance = mock_send.return_value
        instance.send.assert_called_once()
        instance.attach.assert_not_called()

    def test_attaches_pdf_when_provided(self, monkeypatch):
        from unittest.mock import MagicMock
        mock_cls = MagicMock()
        monkeypatch.setattr("website.notifications.EmailMessage", mock_cls)

        from website.notifications import send_certificate_email
        order, cert = self._make_order_cert()
        result = send_certificate_email(order, cert, pdf_bytes=b"%PDF-test")
        assert result is True
        instance = mock_cls.return_value
        instance.attach.assert_called_once_with(
            f"certificate_{cert.code}.pdf",
            b"%PDF-test",
            "application/pdf",
        )
        instance.send.assert_called_once()

    def test_returns_false_if_no_email(self):
        from website.notifications import send_certificate_email
        order, cert = self._make_order_cert(email="")
        order.client_email = ""
        result = send_certificate_email(order, cert)
        assert result is False

    def test_bundle_cert_value_str(self, monkeypatch):
        from unittest.mock import MagicMock
        mock_cls = MagicMock()
        monkeypatch.setattr("website.notifications.EmailMessage", mock_cls)

        bundle = baker.make("services_app.Bundle", name="SPA Комплекс")
        order = baker.make(
            "services_app.Order",
            order_type="certificate",
            client_email="a@b.com",
            total_amount=Decimal("5000"),
        )
        today = date.today()
        cert = baker.make(
            "services_app.GiftCertificate",
            order=order,
            certificate_type="bundle",
            nominal=Decimal("5000"),
            bundle=bundle,
            buyer_name="Андрей",
            valid_from=today,
            valid_until=today + timedelta(days=180),
            status="paid",
        )
        from website.notifications import send_certificate_email
        send_certificate_email(order, cert)
        body = mock_cls.call_args[1]["body"]
        assert "SPA Комплекс" in body


# ── fulfill_paid_certificate с PDF ───────────────────────────────────────────


@pytest.mark.django_db
class TestFulfillPaidCertificatePdf:
    def _make_pending(self):
        order = baker.make(
            "services_app.Order",
            order_type="certificate",
            payment_method="online",
            payment_status="succeeded",
            client_name="Тест",
            client_phone="+79990001122",
            client_email="test@example.com",
            total_amount=Decimal("3000"),
        )
        today = date.today()
        baker.make(
            "services_app.GiftCertificate",
            order=order,
            certificate_type="nominal",
            nominal=Decimal("3000"),
            buyer_name="Тест",
            buyer_phone="+79990001122",
            buyer_email="test@example.com",
            valid_from=today,
            valid_until=today + timedelta(days=180),
            status="pending",
            is_active=False,
        )
        return order

    def test_pdf_generation_called_and_attached(self, monkeypatch):
        mock_pdf = MagicMock(return_value=b"%PDF")
        mock_email = MagicMock(return_value=True)
        mock_tg = MagicMock()
        monkeypatch.setattr("payments.tasks.generate_certificate_pdf", mock_pdf)
        monkeypatch.setattr("payments.tasks.send_certificate_email", mock_email)
        monkeypatch.setattr("payments.tasks.send_notification_telegram", mock_tg)

        from payments.tasks import fulfill_paid_certificate
        order = self._make_pending()
        fulfill_paid_certificate(order.pk)

        mock_pdf.assert_called_once()
        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args[1]
        assert call_kwargs.get("pdf_bytes") == b"%PDF"

    def test_email_sent_even_if_pdf_fails(self, monkeypatch):
        mock_pdf = MagicMock(side_effect=Exception("WeasyPrint unavailable"))
        mock_email = MagicMock(return_value=True)
        mock_tg = MagicMock()
        monkeypatch.setattr("payments.tasks.generate_certificate_pdf", mock_pdf)
        monkeypatch.setattr("payments.tasks.send_certificate_email", mock_email)
        monkeypatch.setattr("payments.tasks.send_notification_telegram", mock_tg)

        from payments.tasks import fulfill_paid_certificate
        order = self._make_pending()
        fulfill_paid_certificate(order.pk)

        mock_email.assert_called_once()
        call_kwargs = mock_email.call_args[1]
        assert call_kwargs.get("pdf_bytes") is None


# ── api_certificate_request: bundle_id ──────────────────────────────────────


@pytest.mark.django_db
class TestCertificateRequestBundleType:
    url = "/api/certificates/request/"

    @pytest.fixture
    def cert_bundle(self, db):
        return baker.make(
            "services_app.Bundle",
            name="SPA Программа",
            is_active=True,
            is_certificate=True,
            fixed_price=Decimal("5000"),
        )

    def test_bundle_creates_cert_with_bundle_fk(self, client, cert_bundle, mock_telegram):
        payload = {
            "certificate_type": "bundle",
            "bundle_id": cert_bundle.id,
            "buyer_name": "Тестов",
            "buyer_phone": "+79990001122",
        }
        resp = client.post(
            self.url, json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

        from services_app.models import GiftCertificate, Order
        order = Order.objects.get(number=data["order_number"])
        cert = GiftCertificate.objects.get(order=order)
        assert cert.certificate_type == "bundle"
        assert cert.bundle_id == cert_bundle.id

    def test_bundle_not_is_certificate_returns_404(self, client, mock_telegram):
        hidden = baker.make(
            "services_app.Bundle",
            name="Скрытый",
            is_active=True,
            is_certificate=False,
        )
        payload = {
            "certificate_type": "bundle",
            "bundle_id": hidden.id,
            "buyer_name": "Тестов",
            "buyer_phone": "+79990001122",
        }
        resp = client.post(
            self.url, json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 404

    def test_bundle_id_missing_returns_400(self, client, mock_telegram):
        payload = {
            "certificate_type": "bundle",
            "buyer_name": "Тестов",
            "buyer_phone": "+79990001122",
        }
        resp = client.post(
            self.url, json.dumps(payload), content_type="application/json"
        )
        assert resp.status_code == 400
