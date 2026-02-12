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
        # показываем среднюю цену за единицу (процедуру/зону/визит)
        try:
            val = (obj.price or 0) / obj.units
        except Exception:
            return "—"
        return f"{val:.0f} ₽/ед."
    price_per_unit_readonly.short_description = "Цена за единицу"

@admin.register(ServiceOption)
class ServiceOptionAdmin(admin.ModelAdmin):
    search_fields = ("name", "service__title", "yclients_service_id", "service__name")  # ищем по названию варианта и названию услуги
    list_display = ("name", "service", "price", "duration_min", "is_active", "yclients_service_id")
    list_filter = ("is_active", "service")

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "short", "category", "image_preview", "is_active", "is_popular")
    list_filter = ("category", "is_active", "is_popular")
    search_fields = ("name",)
    inlines = [ServiceOptionInline]

    change_list_template = "admin/services_app/service/change_list.html"

    fieldsets = (
        ("Основная информация", {
            "fields": ("name", "short", "category", "description", "image")
        }),
        ("Статус", {
            "fields": ("is_active", "is_popular")
        }),
        ("Устаревшие поля (только для чтения)", {
            "fields": ("price", "price_from", "duration", "duration_min"),
            "classes": ("collapse",)
        }),
    )

    readonly_fields = ("price", "price_from", "duration", "duration_min")
    
    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height: 50px; max-width: 50px; object-fit: cover; border-radius: 4px;" />', obj.image.url)
        return "—"
    image_preview.short_description = "Изображение"
    
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
                    for row_num, row in enumerate(reader, start=2):  # с учётом заголовка
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

                # вернуть на список услуг
                from django.shortcuts import redirect
                return redirect("admin:services_app_service_changelist")
        else:
            form = ServiceCSVImportForm()
        return self._render_import_form(request, form)

    def _render_import_form(self, request, form):
        from django.shortcuts import render
        return render(request, "admin/services_app/service/import_form.html", {"form": form})

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
    autocomplete_fields = ('option',)   # удобно, если вариантов много
    fields = ('option', 'quantity', 'order', 'parallel_group', 'gap_after_min')
    extra = 1

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('option', 'option__service')

@admin.register(Bundle)
class BundleAdmin(admin.ModelAdmin):
    exclude = ("services",)

    list_display = ("id", "name", "is_active", "is_popular", "order")
    list_editable = ("is_active", "is_popular", "order")
    list_filter = ("is_active", "is_popular")
    inlines = [BundleItemInline]
    fieldsets = (
        (None, {"fields": ("name", "description", "image", "image_mobile")}),
        ("Цена", {"fields": ("fixed_price", "discount")}),
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
    list_display = ("salon_name","contact_phone","address")


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
