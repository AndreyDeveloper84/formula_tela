"""Payment-specific admin-actions для моделей, живущих в services_app.

Django-идиома: модели Order и GiftCertificate принадлежат services_app
(это core domain), но actions над ними, требующие payments-логики,
живут здесь. Таким образом:

  - services_app/admin.py регистрирует базовые OrderAdmin/GiftCertificateAdmin
    без payments-зависимостей (чистый CRUD + отображение).
  - payments/admin.py подхватывает их, делает subclass с нужными actions,
    unregister + re-register. Импортирует из services_app и notifications —
    правильное направление стрелок (feature → domain).

До этого рефакторинга services_app/admin.py содержал лениво-импортируемые
`from payments.exceptions import …`, `from payments.services import …` и
`from agents.telegram import …` — это был цикл services_app ↔ {payments, agents}.
Теперь цикл разорван: services_app не импортирует payments/agents ни на каком
уровне.

Загружается Django-автодискаверером (admin.py у каждого installed app), порядок
INSTALLED_APPS гарантирует что services_app.admin загрузится раньше payments.admin.
"""
from django.contrib import admin
from django.utils import timezone

from notifications import send_certificate_email, send_notification_telegram
from services_app.admin import GiftCertificateAdmin as _BaseGiftCertAdmin
from services_app.admin import OrderAdmin as _BaseOrderAdmin
from services_app.models import GiftCertificate, Order


class OrderAdmin(_BaseOrderAdmin):
    """OrderAdmin + action пересоздания платёжной ссылки YooKassa."""

    actions = list(_BaseOrderAdmin.actions or []) + ["action_recreate_payment_link"]

    @admin.action(description="Пересоздать платёжную ссылку (YooKassa)")
    def action_recreate_payment_link(self, request, queryset):
        """Пересоздать платёжную ссылку YooKassa для online-заказов.

        Применим к Order(payment_method=online, payment_status in pending/canceled)
        — полезно если клиент потерял ссылку или платёж отменился и хочется
        попробовать заново без создания нового заказа.
        """
        from payments.exceptions import PaymentError
        from payments.services import PaymentService

        done, skipped, failed = 0, 0, 0
        for order in queryset:
            if order.payment_method != "online" or order.payment_status not in ("pending", "canceled"):
                skipped += 1
                continue
            order.payment_id = ""
            order.payment_url = ""
            try:
                PaymentService().create_for_order(order)
                done += 1
            except PaymentError as exc:
                order.admin_note = f"{order.admin_note}\n[recreate] {exc}".strip()
                order.save(update_fields=["admin_note", "updated_at"])
                failed += 1
        self.message_user(
            request,
            f"Пересоздано: {done}, пропущено (не online/pending): {skipped}, ошибок: {failed}",
        )


class GiftCertificateAdmin(_BaseGiftCertAdmin):
    """GiftCertificateAdmin + actions оплаты/вручения/повторной отправки PDF."""

    actions = list(_BaseGiftCertAdmin.actions or []) + [
        "mark_as_paid",
        "mark_as_delivered",
        "resend_certificate_email",
    ]

    @admin.action(description="Отметить как оплаченные")
    def mark_as_paid(self, request, queryset):
        from payments.tasks import fulfill_paid_certificate

        pending = list(queryset.filter(status="pending").select_related("order"))
        if not pending:
            self.message_user(request, "Нет сертификатов в статусе «ожидание»")
            return

        for cert in pending:
            fulfill_paid_certificate.delay(cert.order_id)

        self.message_user(
            request,
            f"Запущена активация {len(pending)} сертификат(а). "
            f"Email с PDF будет отправлен автоматически.",
        )

    @admin.action(description="Отметить как вручённые и отправить в Telegram")
    def mark_as_delivered(self, request, queryset):
        now = timezone.now()
        certs = list(queryset.filter(status="paid").select_related("order", "bundle"))
        if not certs:
            self.message_user(request, "Нет оплаченных сертификатов для вручения")
            return

        queryset.filter(status="paid").update(status="delivered", delivered_at=now)

        sent = 0
        for cert in certs:
            if cert.certificate_type == "nominal":
                value_str = f"{cert.nominal:,.0f} ₽"
            elif cert.certificate_type == "bundle" and cert.bundle:
                value_str = cert.bundle.name
            else:
                value_str = str(cert.service or "—")

            text = (
                f"🎁 Сертификат вручён\n\n"
                f"💳 Код: <b>{cert.code}</b>\n"
                f"💰 {value_str}\n"
                f"👤 Покупатель: {cert.buyer_name}\n"
            )
            if cert.recipient_name:
                text += f"🎀 Получатель: {cert.recipient_name}\n"
            if cert.message:
                text += f"💬 {cert.message}\n"
            text += f"\n✅ Действителен до: {cert.valid_until:%d.%m.%Y}"

            if send_notification_telegram(text):
                sent += 1

        msg = f"Вручено сертификатов: {len(certs)}"
        if sent:
            msg += f", отправлено в Telegram: {sent}"
        self.message_user(request, msg)

    @admin.action(description="Повторно отправить PDF-сертификат на email")
    def resend_certificate_email(self, request, queryset):
        from payments.certificate_pdf import generate_certificate_pdf

        certs = list(queryset.filter(status="paid").select_related("order", "bundle"))
        if not certs:
            self.message_user(
                request, "Нет оплаченных сертификатов для отправки", level="warning"
            )
            return

        sent = 0
        errors = 0
        for cert in certs:
            if not cert.order.client_email:
                continue
            pdf_bytes = None
            try:
                pdf_bytes = generate_certificate_pdf(cert, cert.order)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "resend PDF failed cert=%s: %s", cert.code, exc
                )
                errors += 1
            send_certificate_email(cert.order, cert, pdf_bytes=pdf_bytes)
            sent += 1

        msg = f"Отправлено писем: {sent}"
        if errors:
            msg += f" (PDF не сгенерирован для {errors} шт. — письмо без вложения)"
        self.message_user(request, msg)


# Unregister базовых admin-классов и re-register с payment-actions.
# services_app.admin уже загружен (порядок INSTALLED_APPS гарантирует).
admin.site.unregister(Order)
admin.site.unregister(GiftCertificate)
admin.site.register(Order, OrderAdmin)
admin.site.register(GiftCertificate, GiftCertificateAdmin)
