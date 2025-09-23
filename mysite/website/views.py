from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, HttpResponseBadRequest
from collections import defaultdict
from django.db.models import Prefetch

from services_app.models import SiteSettings, ServiceCategory, Service, Master, FAQ, ServiceOption, Promotion, Bundle, BundleItem

def _settings():
    return SiteSettings.objects.first()

def home(request):
    # Популярные услуги + первый активный вариант ServiceOption для каждой
    from django.db.models import Prefetch
    options_qs = ServiceOption.objects.filter(is_active=True).order_by(
        "order", "duration_min", "unit_type", "units"
    )

    services = (
        Service.objects.filter(is_active=True, is_popular=True)
        .prefetch_related(Prefetch("options", queryset=options_qs))
        .select_related("category")
    )[:6]

    top_items = []
    for svc in services:
        # все активные варианты уже отсортированы в options_qs
        opts = list(svc.options.all())
        top_items.append({"service": svc, "options": opts})

    promos = (
        Promotion.objects.filter(is_active=True)
        .order_by("order", "-starts_at", "title")[:3]
    )

    from django.db.models import Prefetch
    popular_bundles = (
        Bundle.objects.filter(is_active=True, is_popular=True)
        .prefetch_related("items", "items__option", "items__option__service")
        [:3]
    )

    ctx = {
        "settings": _settings(),
        "top_items": top_items,
        "faq": FAQ.objects.filter(is_active=True).order_by("order", "id")[:6],
        "promotions": promos,
        "popular_bundles": popular_bundles,
    }
    return render(request, "website/home.html", ctx)

def services(request):
    categories = (
        ServiceCategory.objects.prefetch_related("services")
        .all()
        .order_by("order", "name")
    )
    return render(request, "website/services.html", {
        "settings": _settings(),
        "categories": categories,
    })


def promotions(request):
    items = (
        Promotion.objects.filter(is_active=True)
        .prefetch_related("options", "options__service")
        .order_by("order", "-starts_at", "title")
    )
    return render(request, "website/promotions.html", {
        "settings": _settings(),
        "promotions": items,
    })


def masters(request):
    items = Master.objects.filter(is_active=True).prefetch_related("services").all().order_by("name")
    return render(request, "website/masters.html", {
        "settings": _settings(),
        "masters": items,
    })

def contacts(request):
    return render(request, "website/contacts.html", {
        "settings": _settings(),
    })

def book_service(request):
    option_id = request.GET.get("service_option_id")
    if not option_id:
        return HttpResponseBadRequest("service_option_id is required")

    option = get_object_or_404(ServiceOption, pk=option_id, is_active=True)
    # здесь можно сразу редиректить в модуль бронирования/yclients,
    # а пока — покажем страницу подтверждения
    return render(request, "website/book_service_preview.html", {"option": option})

def _min_option(service):
    """Возвращает самый «лёгкий» вариант (для стартового подсчёта)."""
    opts = list(service.options.all())
    return opts[0] if opts else None


def bundles(request):

    def _compute_min_totals(items):
    # сгруппируем элементы по parallel_group
        groups = defaultdict(list)
        gaps_total = 0
        for it in items:
            groups[it.parallel_group].append(it)
            gaps_total += int(it.gap_after_min or 0)

        total_price = 0
        total_duration = 0
        for items in groups.values():
            gmax = 0
            for it in items:
                opt = it.option  # ← берём ровно то, что выбрано в админке
                if not opt:
                    continue
                total_price += opt.price or 0
                gmax = max(gmax, int(opt.duration_min or 0))
            total_duration += gmax

        total_duration += gaps_total
        return total_price, total_duration


    # варианты для услуг
    opt_qs = (ServiceOption.objects
              .filter(is_active=True)
              .order_by("order", "duration_min", "unit_type", "units"))

    svc_qs = (Service.objects
              .prefetch_related(Prefetch("options", queryset=opt_qs)))

    # элементы комплексов
    items_qs = (BundleItem.objects
                .select_related("bundle", "option", "option__service")
                .prefetch_related(Prefetch("option__service", queryset=svc_qs))
                .order_by("order"))

    # сами комплексы
    bundles_qs = (Bundle.objects
                  .filter(is_active=True)
                  .prefetch_related(Prefetch("items", queryset=items_qs)))

    # подготовим удобную структуру для шаблона
    bundles = []
    for b in bundles_qs:
        # получим элементы и посчитаем «минимальные» итоги
        items = list(b.items.all())
        min_price, min_duration = _compute_min_totals(items)
        price = b.fixed_price
        # не трогаем b.items (related manager), складываем в структуру
        bundles.append({
            "bundle": b,
            "items": items,
            "min_price": min_price,
            "min_duration": min_duration,
            "price": price})
    
    return render(request, "website/bundles.html", {
        "settings": _settings(),
        "bundles": bundles,
    })
