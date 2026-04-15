from django.contrib import admin, messages
from django.urls import path
from django.utils.html import format_html
from django.db import transaction
from decimal import Decimal, InvalidOperation
import csv, io

from .models import (
    Service,
    Master,
    ServicePackage,
    ServiceCategory,
    Bundle,
    BundleItem,
    FAQ,
    SiteSettings,
    ServiceOption,
    Promotion,
    Review,
    BundleRequest,
    BookingRequest,
    ServiceBlock,
    ServiceMedia,
    Order,
    GiftCertificate,
    CertificateRedemption,
)

from .forms import ServiceCSVImportForm

@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ("id","name","description", "slug", "image_preview", "order")
    list_editable = ("name", "description", "order")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    fields = ("name", "slug", "description", "order", "image", "image_mobile")

    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height:40px;max-width:60px;'
                'object-fit:cover;border-radius:4px;" />',
                obj.image.url
            )
        return "—"
    image_preview.short_description = "Фото"

class ServiceOptionInline(admin.TabularInline):
    model = ServiceOption
    extra = 0
    fields = ("order", "duration_min", "unit_type", "units", "price", "price_per_unit_readonly", "is_active", "yclients_service_id")
    readonly_fields = ("price_per_unit_readonly",)
    ordering = ("order", "duration_min", "unit_type", "units")  

    def price_per_unit_readonly(self, obj):
        if not obj or not obj.units:
            return "—"
        try:
            val = (obj.price or 0) / obj.units
        except Exception:
            return "—"
        return f"{val:.0f} ₽/ед."
    price_per_unit_readonly.short_description = "Цена за единицу"

@admin.register(ServiceOption)
class ServiceOptionAdmin(admin.ModelAdmin):
    search_fields = ("name", "service__title", "yclients_service_id", "service__name")
    list_display = ("name", "service", "price", "duration_min", "is_active", "yclients_service_id")
    list_filter = ("is_active", "service")


class ServiceBlockInline(admin.StackedInline):
    """Inline-редактор контентных блоков на странице услуги"""
    model = ServiceBlock
    extra = 0
    ordering = ("order",)
    classes = ("collapse",)
    verbose_name = "Контентный блок"
    verbose_name_plural = "📝 Контентные блоки (лендинг)"

    fieldsets = (
        (None, {
            "fields": ("order", "is_active", "block_type", "heading_level", "title")
        }),
        ("Содержимое", {
            "fields": ("content",),
            "description": (
                "<b>Форматы заполнения:</b><br>"
                "• <b>Текст / Акцент / HTML / Форматы / Абонементы:</b> HTML-контент<br>"
                "• <b>Чеклист / Идентификация:</b> каждый пункт с новой строки<br>"
                "• <b>FAQ:</b> Вопрос?<br>Текст ответа.<br>---<br>Вопрос?<br>Текст ответа.<br>"
                "&nbsp;&nbsp;(разделитель между вопросами — строка из трёх дефисов: <code>---</code>)<br>"
                "• <b>CTA:</b> оставьте пустым (используется только кнопка)<br>"
                "• <b>Таблица цен:</b> HTML-таблица<br>"
                "• <b>Аккордеон:</b> HTML-контент (раскрывается по клику на заголовок)"
            ),
        }),
        ("Оформление", {
            "fields": ("bg_color", "text_color", "btn_text", "btn_sub", "css_class"),
            "classes": ("collapse",),
            "description": (
                "<b>Какие поля для какого типа:</b><br>"
                "• <b>Акцентный блок:</b> Цвет фона (#9BAE9E), Цвет текста (#fff)<br>"
                "• <b>CTA-кнопка:</b> Текст кнопки, Подпись под кнопкой<br>"
                "• <b>Навигация:</b> Цвет фона (#F5F5F5)<br>"
                "• <b>Остальные:</b> можно не заполнять"
            ),
        }),
    )

class ServiceMediaInline(admin.StackedInline):
    """Inline-редактор медиа-файлов на странице услуги"""
    model = ServiceMedia
    extra = 0
    ordering = ("order",)
    classes = ("collapse",)
    verbose_name = "Медиа-файл"
    verbose_name_plural = "📷 Медиа-файлы (фото/видео)"

    fieldsets = (
        (None, {
            "fields": ("order", "is_active", "media_type", "display_mode", "carousel_group")
        }),
        ("Файлы", {
            "fields": ("image", "image_mobile", "video_file", "video_url"),
            "description": (
                "<b>Для фото:</b> загрузите изображение. Мобильная версия — опционально.<br>"
                "<b>Для видео:</b> вставьте embed-ссылку YouTube. Пример: https://www.youtube.com/embed/XXXXX"
            ),
        }),
        ("SEO и позиция", {
            "fields": ("alt_text", "title_text", "insert_after_order"),
            "classes": ("collapse",),
            "description": (
                "<b>insert_after_order</b> — на мобильном медиа вставится после блока с этим порядком.<br>"
                "Например: 20 = после чеклиста, 50 = после таблицы цен."
            ),
        }),
    )


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "short", "category", "slug", "image_preview", "order", "is_active", "is_popular")
    list_filter = ("category", "is_active", "is_popular")
    list_editable = ("order", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [ServiceOptionInline, ServiceBlockInline, ServiceMediaInline]

    change_list_template = "admin/services_app/service/change_list.html"

    fieldsets = (
        ("Основная информация", {
            "fields": ("name", "short", "slug", "category", "order")
        }),
        ("SEO", {
            "fields": ("seo_title", "seo_description", "seo_h1", "subtitle"),
            "classes": ("collapse",),
            "description": "Поля для поисковой оптимизации. Если пусто — используются значения по умолчанию."
        }),
        ("Контент", {
            "fields": ("description", "image", "image_mobile"),
        }),
        ("Перелинковка", {
            "fields": ("related_services",),
            "classes": ("collapse",),
            "description": (
                "Выберите услуги для блока «Другие виды массажа» внизу страницы. "
                "Фото, название и цена подтягиваются автоматически из выбранных услуг."
            ),
        }),
        ("Статус", {
            "fields": ("is_active", "is_popular")
        }),
        ("Устаревшие поля (только для чтения)", {
            "fields": ("price", "price_from", "duration", "duration_min"),
            "classes": ("collapse",)
        }),
    )

    filter_horizontal = ('related_services',)

    readonly_fields = ("price", "price_from", "duration", "duration_min")
    
    def image_preview(self, obj):
        if obj.image:
            return format_html(
                '<img src="{}" style="max-height: 50px; max-width: 50px; '
                'object-fit: cover; border-radius: 4px;" />', obj.image.url
            )
        return "—"
    image_preview.short_description = "Фото"
    
    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path("import-csv/", self.admin_site.admin_view(self.import_csv_view), name="service_import_csv"),
        ]
        return custom + urls

    def import_csv_view(self, request):
        if request.method == "POST":
            form = ServiceCSVImportForm(request.POST, request.FILES)
            if form.is_valid():
                file = request.FILES["file"]
                delimiter = form.cleaned_data["delimiter"]
                update_existing = form.cleaned_data["update_existing"]

                try:
                    data = file.read().decode("utf-8-sig")
                except UnicodeDecodeError:
                    messages.error(request, "Не удалось прочитать файл как UTF-8. Проверьте кодировку.")
                    return self._render_import_form(request, form)

                reader = csv.DictReader(io.StringIO(data), delimiter=delimiter)
                required = {"category","name","price_from","duration_min","is_active"}
                missing = required - set([h.strip() for h in reader.fieldnames or []])
                if missing:
                    messages.error(request, f"В CSV отсутствуют колонки: {', '.join(sorted(missing))}")
                    return self._render_import_form(request, form)

                created = updated = skipped = 0
                errors = []

                @transaction.atomic
                def process():
                    nonlocal created, updated, skipped
                    for row_num, row in enumerate(reader, start=2):
                        try:
                            cat_name = (row.get("category") or "").strip()
                            name = (row.get("name") or "").strip()
                            short = (row.get("short") or "").strip()
                            description = (row.get("description") or "").strip()
                            price_raw = (row.get("price_from") or "").strip()
                            duration_raw = (row.get("duration_min") or "").strip()
                            is_active_raw = (row.get("is_active") or "").strip()

                            if not cat_name or not name:
                                skipped += 1
                                continue

                            try:
                                price = Decimal(price_raw.replace(",", "."))
                            except (InvalidOperation, AttributeError):
                                raise ValueError(f"Некорректная цена '{price_raw}'")

                            try:
                                duration = int(duration_raw)
                                if duration <= 0:
                                    raise ValueError
                            except Exception:
                                raise ValueError(f"Некорректная длительность '{duration_raw}' (нужно целое > 0)")

                            is_active = str(is_active_raw).strip().lower() in {"1","true","да","y","yes","on"}

                            category, _ = ServiceCategory.objects.get_or_create(name=cat_name)

                            qs = Service.objects.filter(category=category, name=name)
                            if qs.exists():
                                if update_existing:
                                    svc = qs.first()
                                    svc.short = short
                                    svc.description = description
                                    svc.price_from = price
                                    svc.price = price
                                    svc.duration_min = duration
                                    svc.is_active = is_active
                                    svc.save()
                                    updated += 1
                                else:
                                    skipped += 1
                            else:
                                Service.objects.create(
                                    category=category, name=name, short=short,
                                    description=description, price_from=price, price=price,
                                    duration_min=duration, is_active=is_active
                                )
                                created += 1

                        except Exception as e:
                            errors.append(f"Строка {row_num}: {e}")

                process()

                if created: messages.success(request, f"Создано: {created}")
                if updated: messages.success(request, f"Обновлено: {updated}")
                if skipped: messages.info(request, f"Пропущено: {skipped}")
                for e in errors[:10]:
                    messages.error(request, e)
                if len(errors) > 10:
                    messages.error(request, f"И ещё ошибок: {len(errors) - 10}")

                from django.shortcuts import redirect
                return redirect("admin:services_app_service_changelist")
        else:
            form = ServiceCSVImportForm()
        return self._render_import_form(request, form)

    def _render_import_form(self, request, form):
        from django.shortcuts import render
        return render(request, "admin/services_app/service/import_form.html", {"form": form})


@admin.register(ServiceBlock)
class ServiceBlockAdmin(admin.ModelAdmin):
    list_display = ("id", "service", "block_type", "title", "order", "is_active")
    list_filter = ("block_type", "is_active", "service")
    list_editable = ("order", "is_active")
    search_fields = ("title", "content", "service__name")
    ordering = ("service", "order")


@admin.register(Master)
class MasterAdmin(admin.ModelAdmin):
    list_display = ["name", "specialization", "order", "is_active", "photo_preview"]
    list_editable = ["order", "is_active"]
    list_filter = ("is_active", "specialization")
    search_fields = ("name", "specialization")
    prepopulated_fields = {}
    fieldsets = (
         (None, {
             "fields": ("name", "specialization", "experience", "is_active", "order")
         }),
         ("Фото", {
             "fields": ("photo", "photo_mobile"),
         }),
         ("Контакты", {
             "fields": ("phone", "email", "working_hours"),
            "classes": ("collapse",),
         }),
         ("Accordion: Образование", {
             "fields": ("education",),
             "classes": ("collapse",),
             "description": "HTML: используйте <h2> для подзаголовков, <ul><li> для списков"
         }),
         ("Accordion: Опыт работы", {
             "fields": ("work_experience",),
             "classes": ("collapse",),
         }),
         ("Accordion: Подход к работе", {
             "fields": ("approach",),
             "classes": ("collapse",),
         }),
         ("Accordion: Отзывы и статистика", {
             "fields": ("reviews_text",),
             "classes": ("collapse",),
         }),
         ("Описание (старое поле)", {
             "fields": ("bio",),
             "classes": ("collapse",),
         }),
         ("Услуги", {
             "fields": ("services",),
         }),
     )
    filter_horizontal = ["services"]
    def photo_preview(self, obj):
        if obj.photo:
            return format_html('<img src="{}" style="height:40px; border-radius:4px;" />', obj.photo.url)
        return "—"
    photo_preview.short_description = "Фото"

class BundleItemInline(admin.TabularInline):
    model = BundleItem
    autocomplete_fields = ('option',)
    fields = ('option', 'quantity', 'order', 'parallel_group', 'gap_after_min')
    extra = 1

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('option', 'option__service')

@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "slug", "is_active", "is_popular", "order")
    list_editable = ("is_active", "is_popular", "order")
    list_filter = ("is_active", "is_popular")
    search_fields = ("name", "description", "slug", "seo_title")
    prepopulated_fields = {"slug": ("name",)}
    inlines = [BundleItemInline]
    fieldsets = (
        (None, {"fields": ("name", "description", "image", "image_mobile")}),
        ("Цена", {"fields": ("fixed_price",)}),
        ("SEO", {
            "fields": ("slug", "seo_h1", "seo_title", "seo_description", "subtitle"),
            "description": "URL вида /kompleks/<slug>/. slug автозаполняется из названия.",
        }),
        ("Настройки", {"fields": ("is_active", "is_popular", "order")}),
    )


@admin.register(BundleItem)
class BundleItemAdmin(admin.ModelAdmin):
    list_display = ('bundle', 'service_name', 'option_name', 'quantity', 'order', 'parallel_group', 'gap_after_min')
    autocomplete_fields = ('option',)

    def service_name(self, obj):
        return obj.option.service if obj.option_id else '-'
    service_name.short_description = 'Услуга'

    def option_name(self, obj):
        return obj.option.name if obj.option_id else '-'
    option_name.short_description = 'Вариант'

@admin.register(BundleRequest)
class BundleRequestAdmin(admin.ModelAdmin):
    list_display = ("id", "client_name", "client_phone", "bundle_name", "is_processed", "created_at")
    list_filter = ("is_processed", "created_at")
    list_editable = ("is_processed",)
    search_fields = ("client_name", "client_phone", "bundle_name")
    readonly_fields = ("bundle", "bundle_name", "client_name", "client_phone", "client_email", "comment", "created_at")

@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "category", "question", "is_active")
    list_display_links = ("question",)
    list_editable = ("order", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("question", "answer")
    ordering = ("order", "id")

@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("salon_name", "contact_phone", "address")
    fieldsets = (
        ("Основное", {
            "fields": (
                "site_name", "salon_name", "logo", "description",
            ),
        }),
        ("Контакты", {
            "fields": (
                "contact_email", "contact_phone", "address", "working_hours",
            ),
        }),
        ("Уведомления", {
            "fields": ("notification_emails",),
            "description": (
                "Email-адреса для уведомлений о заявках с формы-мастера "
                "(кнопка «Записаться онлайн» и CTA на страницах услуг). "
                "По одному адресу на строку."
            ),
        }),
        ("Интеграции и карты", {
            "fields": (
                "yclients_link", "yclients_company_id",
                "google_maps_link", "yandex_maps_link",
            ),
        }),
        ("Контент и соцсети", {
            "fields": (
                "social_media", "payment_methods",
                "cancellation_policy", "privacy_policy",
                "terms_of_service", "copyright",
            ),
        }),
        ("Реквизиты организации", {
            "fields": (
                "legal_name", "legal_address", "inn", "ogrn",
                "bank_name", "bank_account", "bank_bik", "bank_corr_account",
            ),
            "description": (
                "Публикуются на странице /contacts/ в разделе «Реквизиты», "
                "используются в оферте и footer. Требуются для модерации YooKassa."
            ),
        }),
    )


@admin.register(ServicePackage)
class PackageAdmin(admin.ModelAdmin):
    list_display = ("title", "total_price", "is_popular")
    list_filter = ("is_popular",)
    filter_horizontal = ("services",)


@admin.register(Promotion)
class PromotionAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "title", "is_active", "starts_at", "ends_at")
    list_editable = ("order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("title", "subtitle", "description")
    filter_horizontal = ("options",)
    ordering = ("order", "-starts_at", "title")

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "author_name", "rating", "date", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("is_active", "rating")
    search_fields = ("author_name", "text")
    ordering = ("order", "-date", "-created_at")
    fieldsets = (
        ("Основная информация", {
            "fields": ("author_name", "text", "rating", "date")
        }),
        ("Настройки", {
            "fields": ("is_active", "order")
        }),
    )

@admin.register(BookingRequest)
class BookingRequestAdmin(admin.ModelAdmin):
    list_display = ("client_name", "client_phone", "service_name", "is_processed", "created_at")
    list_filter = ("is_processed", "created_at")
    list_editable = ("is_processed",)
    search_fields = ("client_name", "client_phone", "service_name")
    readonly_fields = ("created_at",)


# ── Заказы и сертификаты ──────────────────────────────────────────────


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number", "order_type", "client_name", "client_phone",
        "total_amount", "status", "created_at",
    )
    list_filter = ("status", "order_type", "created_at")
    list_editable = ("status",)
    search_fields = ("number", "client_name", "client_phone", "client_email")
    readonly_fields = ("number", "created_at", "updated_at")
    fieldsets = (
        ("Заказ", {"fields": ("number", "order_type", "status", "total_amount")}),
        ("Клиент", {"fields": ("client_name", "client_phone", "client_email")}),
        ("Оплата", {
            "fields": ("payment_method", "payment_id", "paid_at"),
            "classes": ["collapse"],
        }),
        ("Примечания", {"fields": ("comment", "admin_note")}),
        ("Даты", {"fields": ("created_at", "updated_at")}),
    )


class CertificateRedemptionInline(admin.TabularInline):
    model = CertificateRedemption
    extra = 0
    readonly_fields = ("created_at",)
    fields = ("amount", "service_name", "redeemed_by", "note", "created_at")


@admin.register(GiftCertificate)
class GiftCertificateAdmin(admin.ModelAdmin):
    list_display = (
        "code", "certificate_type", "nominal_display",
        "buyer_name", "recipient_name", "status",
        "valid_until", "created_at",
    )
    list_filter = ("status", "certificate_type", "is_active", "created_at")
    list_editable = ("status",)
    search_fields = (
        "code", "buyer_name", "buyer_phone",
        "recipient_name", "recipient_phone",
    )
    readonly_fields = (
        "code", "created_at", "updated_at",
        "paid_at", "delivered_at", "redeemed_at",
    )
    autocomplete_fields = ("service", "service_option", "order")
    inlines = [CertificateRedemptionInline]

    fieldsets = (
        ("Сертификат", {"fields": (
            "code", "certificate_type", "nominal",
            "service", "service_option", "order", "image",
        )}),
        ("Покупатель", {"fields": (
            "buyer_name", "buyer_phone", "buyer_email",
        )}),
        ("Получатель", {"fields": (
            "recipient_name", "recipient_phone", "message",
        )}),
        ("Статус", {"fields": (
            "status", "is_active", "valid_from", "valid_until",
        )}),
        ("Даты", {"fields": (
            "paid_at", "delivered_at", "redeemed_at",
            "created_at", "updated_at",
        )}),
        ("Примечания", {
            "fields": ("admin_note",),
            "classes": ["collapse"],
        }),
    )

    actions = ["mark_as_paid", "mark_as_delivered"]

    @admin.display(description="Номинал")
    def nominal_display(self, obj):
        if obj.certificate_type == "nominal":
            return f"{obj.nominal:,.0f} \u20bd"
        return str(obj.service or "\u2014")

    @admin.action(description="Отметить как оплаченные")
    def mark_as_paid(self, request, queryset):
        from django.utils import timezone
        updated = queryset.filter(status="pending").update(
            status="paid", paid_at=timezone.now(),
        )
        self.message_user(request, f"Оплачено сертификатов: {updated}")

    @admin.action(description="Отметить как вручённые и отправить в Telegram")
    def mark_as_delivered(self, request, queryset):
        from django.utils import timezone
        import requests as http_requests
        from django.conf import settings as django_settings
        import logging

        now = timezone.now()
        certs = list(queryset.filter(status="paid"))
        if not certs:
            self.message_user(request, "Нет оплаченных сертификатов для вручения")
            return

        queryset.filter(status="paid").update(status="delivered", delivered_at=now)

        tg_token = getattr(django_settings, "TELEGRAM_BOT_TOKEN", "")
        tg_chat = getattr(django_settings, "TELEGRAM_CHAT_ID", "")
        sent = 0

        for cert in certs:
            if not (tg_token and tg_chat):
                break
            try:
                value_str = (
                    f"{cert.nominal:,.0f} \u20bd"
                    if cert.certificate_type == "nominal"
                    else str(cert.service or "\u2014")
                )
                caption = (
                    f"\U0001f381 \u041f\u043e\u0434\u0430\u0440\u043e\u0447\u043d\u044b\u0439 \u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442\n\n"
                    f"\U0001f4b3 \u041a\u043e\u0434: <b>{cert.code}</b>\n"
                    f"\U0001f4b0 {value_str}\n"
                    f"\U0001f464 \u041f\u043e\u043a\u0443\u043f\u0430\u0442\u0435\u043b\u044c: {cert.buyer_name}\n"
                )
                if cert.recipient_name:
                    caption += f"\U0001f380 \u041f\u043e\u043b\u0443\u0447\u0430\u0442\u0435\u043b\u044c: {cert.recipient_name}\n"
                if cert.message:
                    caption += f"\U0001f4ac {cert.message}\n"
                caption += (
                    f"\n\u2705 \u0414\u0435\u0439\u0441\u0442\u0432\u0443\u0435\u0442 \u0434\u043e: {cert.valid_until:%d.%m.%Y}"
                )

                if cert.image:
                    with cert.image.open("rb") as img:
                        http_requests.post(
                            f"https://api.telegram.org/bot{tg_token}/sendPhoto",
                            data={
                                "chat_id": tg_chat,
                                "caption": caption,
                                "parse_mode": "HTML",
                            },
                            files={"photo": (cert.image.name, img, "image/jpeg")},
                            timeout=10,
                        )
                else:
                    http_requests.post(
                        f"https://api.telegram.org/bot{tg_token}/sendMessage",
                        json={
                            "chat_id": tg_chat,
                            "text": caption,
                            "parse_mode": "HTML",
                        },
                        timeout=5,
                    )
                sent += 1
            except Exception as e:
                logging.getLogger(__name__).warning(
                    f"Telegram send failed for {cert.code}: {e}"
                )

        msg = f"Вручено сертификатов: {len(certs)}"
        if sent:
            msg += f", отправлено в Telegram: {sent}"
        self.message_user(request, msg)

