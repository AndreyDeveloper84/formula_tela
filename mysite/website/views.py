from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from collections import defaultdict
from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from django_ratelimit.decorators import ratelimit
from services_app.yclients_api import get_yclients_api, YClientsAPIError
import logging
import json
import requests as http_requests
from django.conf import settings as django_settings

from .utils import normalize_ru_phone

from django.core.cache import cache
import hashlib

# TTL для idempotency-ключей бронирования. 60 секунд покрывает double-click
# и retry после сетевого глитча; осознанная повторная запись через минуту
# уже считается валидной и бьёт YClients заново.
BOOKING_IDEMPOTENCY_TTL = 60


def _booking_idempotency_key(*parts: str) -> str:
    """Собирает стабильный ключ кэша из частей бронирования."""
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"booking-idem:{digest}"

from services_app.models import (
    SiteSettings,
    ServiceCategory,
    Service,
    Master,
    FAQ,
    ServiceOption,
    Promotion,
    Bundle,
    BundleItem,
    Review,
    BookingRequest,
    Order,
    GiftCertificate,
)


def _settings():
    return SiteSettings.objects.first()

def home(request):
    # Популярные услуги + первый активный вариант ServiceOption для каждой
    services = Service.objects.active().popular().with_options().with_category()[:6]

    top_items = []
    for svc in services:
        # все активные варианты уже отсортированы в options_qs
        opts = list(svc.options.all())
        top_items.append({"service": svc, "options": opts})

    # Категории услуг для секции "Услуги салона"
    categories = ServiceCategory.objects.with_active_services().order_by("order", "name")[:8]

    # Мастера для секции "Наши мастера"
    masters = Master.objects.active().with_services().order_by("name")[:4]

    promos = Promotion.objects.active()[:3]

    popular_bundles_qs = (
        Bundle.objects.active().popular().with_items().order_by("order", "id")[:3]
    )
    popular_bundles = []
    for b in popular_bundles_qs:
        min_price, min_duration = b.compute_min_totals()
        popular_bundles.append({
            "bundle":       b,
            "min_price":    min_price,
            "min_duration": min_duration,
            "price":        b.fixed_price or min_price,
        })

    reviews = Review.objects.active()[:3]

    ctx = {
        "settings": _settings(),
        "top_items": top_items,
        "categories": categories,
        "masters": masters,
        "faq": FAQ.objects.filter(is_active=True).order_by("order", "id")[:6],
        "promotions": promos,
        "popular_bundles": popular_bundles,
        "reviews": reviews,
    }
    return render(request, "website/home.html", ctx)

def services(request):
    categories = (
        ServiceCategory.objects.prefetch_related("services")
        .all()
        .order_by("order", "name")
    )
    
    # Промо для баннера (если нужно)
    promos = Promotion.objects.active()[:1]

    return render(request, "website/services.html", {
        "settings": _settings(),
        "categories": categories,
        "promotions": promos,
    })


def promotions(request):
    items = Promotion.objects.active().with_options()
    return render(request, "website/promotions.html", {
        "settings": _settings(),
        "promotions": items,
    })


def masters(request):
    items = Master.objects.active().with_services_and_options()
    return render(request, "website/masters.html", {
        "settings": _settings(),
        "masters": items,
    })


def master_detail_by_slug(request, slug):
    """ЧПУ-страница мастера: /masters/<slug>/."""
    svc_qs = Service.objects.active().with_category().prefetch_related("options")
    master = get_object_or_404(
        Master.objects.prefetch_related(Prefetch("services", queryset=svc_qs)),
        slug=slug,
        is_active=True,
    )
    return _render_master_detail(request, master)


def master_detail(request, master_id):
    """Legacy-роут /master/<id>/. 301 на ЧПУ если slug есть."""
    master = get_object_or_404(Master, pk=master_id, is_active=True)
    if master.slug:
        from django.shortcuts import redirect
        return redirect("website:master_detail_by_slug", slug=master.slug, permanent=True)
    return _render_master_detail(request, master)


def _render_master_detail(request, master):
    """Общая сборка контекста детальной страницы мастера."""
    services_qs = list(
        master.services.active().with_category().prefetch_related("options")
    )
    other_masters = list(
        Master.objects.active().exclude(pk=master.pk).order_by("order", "name")[:3]
    )

    seo_title = f"{master.name} — {master.specialization or 'мастер'} | Формула тела"
    bio_text = (master.bio or "").strip()
    if bio_text:
        seo_description = bio_text[:160]
    else:
        parts = [master.name]
        if master.specialization:
            parts.append(master.specialization)
        if master.experience:
            parts.append(f"стаж {master.experience}")
        seo_description = (
            ", ".join(parts)
            + ". Запись в студию эстетики «Формула тела» в Пензе."
        )[:160]

    context = {
        "settings":        _settings(),
        "master":          master,
        "services":        services_qs,
        "other_masters":   other_masters,
        "seo_title":       seo_title,
        "seo_description": seo_description,
    }
    return render(request, "website/master_detail.html", context)


def contacts(request):
    stats = [
        {"icon": "💆", "value": "50+",       "label": "видов процедур"},
        {"icon": "⭐", "value": "5",          "label": "мастеров"},
        {"icon": "📅", "value": "с 2020",     "label": "года работаем"},
        {"icon": "🕐", "value": "9:00–21:00", "label": "ежедневно"},
    ]
    values = [
        {"icon": "🎓", "title": "Профессионализм",
         "desc": "Сертифицированные специалисты с профильным образованием"},
        {"icon": "🌿", "title": "Натуральный уход",
         "desc": "Профессиональные масла и средства премиум-класса"},
        {"icon": "🤝", "title": "Индивидуальный подход",
         "desc": "Программа подбирается под каждого клиента"},
        {"icon": "💰", "title": "Честные цены",
         "desc": "Прозрачный прайс, курсы со скидкой до 20%"},
    ]
    return render(request, "website/contacts.html", {
        "settings": _settings(),
        "stats":    stats,
        "values":   values,
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
    svc_qs = Service.objects.with_options()

    items_qs = (BundleItem.objects
                .select_related("bundle", "option", "option__service")
                .prefetch_related(Prefetch("option__service", queryset=svc_qs))
                .order_by("order"))

    bundles_qs = (Bundle.objects.active()
                  .prefetch_related(Prefetch("items", queryset=items_qs))
                  .order_by("order", "id"))

    bundles = []
    for b in bundles_qs:
        items = list(b.items.all())
        min_price, min_duration = b.compute_min_totals()
        bundles.append({
            "bundle": b,
            "items": items,
            "min_price": min_price,
            "min_duration": min_duration,
            "price": b.fixed_price,
        })

    # Лечебные комплексы — услуги с "комплекс" в названии.
    # Нестандартный порядок (units, duration_min) — используем with_options и
    # .order_by поверх для этой выборки.
    complex_opt_qs = (ServiceOption.objects.active()
                      .order_by("order", "units", "duration_min"))
    complex_services = (Service.objects.active()
                        .filter(name__icontains='комплекс')
                        .prefetch_related(Prefetch('options', queryset=complex_opt_qs))
                        .order_by('name'))

    return render(request, "website/bundles.html", {
        "settings": _settings(),
        "bundles": bundles,
        "complex_services": complex_services,
    })


def bundle_detail_by_slug(request, slug):
    """Детальная страница комплекса по ЧПУ-url /kompleks/<slug>/."""
    svc_qs = Service.objects.with_options()
    items_qs = (BundleItem.objects
                .select_related("option", "option__service", "option__service__category")
                .prefetch_related(Prefetch("option__service", queryset=svc_qs))
                .order_by("order"))

    bundle = get_object_or_404(
        Bundle.objects.prefetch_related(Prefetch("items", queryset=items_qs)),
        slug=slug,
        is_active=True,
    )
    return _render_bundle_detail(request, bundle)


def bundle_detail(request, bundle_id):
    """Legacy-роут /bundle/<id>/. Если у комплекса есть slug — 301 на ЧПУ."""
    bundle = get_object_or_404(Bundle, pk=bundle_id, is_active=True)
    if bundle.slug:
        from django.shortcuts import redirect
        return redirect("website:bundle_detail_by_slug", slug=bundle.slug, permanent=True)
    return _render_bundle_detail(request, bundle)


def _render_bundle_detail(request, bundle):
    """Сборка контекста детальной страницы комплекса."""
    items = list(bundle.items.all())
    min_price, min_duration = bundle.compute_min_totals()
    price = bundle.fixed_price if bundle.fixed_price is not None else min_price

    # Похожие комплексы — другие активные, кроме этого
    other_bundles_qs = (
        Bundle.objects.active().exclude(pk=bundle.pk).order_by("order", "id")[:3]
    )
    other_bundles = []
    for b in other_bundles_qs:
        b_min_price, b_min_duration = b.compute_min_totals()
        other_bundles.append({
            "bundle":       b,
            "price":        b.fixed_price if b.fixed_price is not None else b_min_price,
            "min_duration": b_min_duration,
        })

    seo_title = bundle.seo_title or f"{bundle.name} — комплекс услуг"
    seo_description = bundle.seo_description or (
        bundle.description[:160] if bundle.description else ""
    )
    seo_h1 = bundle.seo_h1 or bundle.name

    context = {
        "settings":        _settings(),
        "bundle":          bundle,
        "items":           items,
        "price":           price,
        "min_price":       min_price,
        "min_duration":    min_duration,
        "other_bundles":   other_bundles,
        "seo_title":       seo_title,
        "seo_description": seo_description,
        "seo_h1":          seo_h1,
        "subtitle":        bundle.subtitle,
    }
    return render(request, "website/bundle_detail.html", context)


logger = logging.getLogger(__name__)

"""
ОБНОВЛЁННАЯ функция api_available_times с фильтрацией по seance_length

ИЗМЕНЕНИЯ:
1. Добавлен параметр service_option_id (для получения длительности процедуры)
2. Фильтрация слотов по seance_length
3. Детальное логирование для отладки
"""

from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import logging

logger = logging.getLogger(__name__)


@require_GET
@csrf_exempt
@ratelimit(key="ip", rate="30/m", method="GET", block=True)
def api_available_times(request):
    """
    API: получить список доступных времён для записи с фильтрацией по длительности
    
    GET параметры:
        - staff_id: ID мастера (обязательно)
        - date: Дата в формате YYYY-MM-DD (обязательно)
        - service_option_id: ID варианта услуги (опционально, для фильтрации)
    
    Возвращает:
        {
            "success": true,
            "data": {
                "times": ["15:00", "16:00"],
                "count": 2,
                "date": "2026-01-08",
                "staff_id": "4354560",
                "filtered": true,  // Была ли применена фильтрация
                "duration_minutes": 60  // Длительность процедуры
            }
        }
    """
    try:
        from services_app.yclients_api import get_yclients_api, YClientsAPIError
        from services_app.models import ServiceOption
        
        # Получаем параметры
        staff_id = request.GET.get('staff_id')
        date = request.GET.get('date')
        service_option_id = request.GET.get('service_option_id')  # ← НОВОЕ!
        
        # Валидация обязательных параметров
        if not staff_id or not date:
            return JsonResponse({
                'success': False,
                'error': 'staff_id and date are required'
            }, status=400)
        
        logger.info(
            f"⏰ Запрос доступных времён: мастер={staff_id}, дата={date}, "
            f"service_option_id={service_option_id}"
        )
        
        # Получаем длительность процедуры (если указан service_option_id)
        duration_minutes = None
        yclients_service_id = None
        
        if service_option_id:
            try:
                option = ServiceOption.objects.get(
                    id=service_option_id,
                    is_active=True
                )
                duration_minutes = option.duration_min
                yclients_service_id = option.yclients_service_id
                
                logger.info(
                    f"📋 Процедура: {option.service.name} "
                    f"(длительность: {duration_minutes} мин, "
                    f"YClients ID: {yclients_service_id})"
                )
                
            except ServiceOption.DoesNotExist:
                logger.warning(f"⚠️ ServiceOption {service_option_id} не найден")
        
        # Запрос к YClients API
        api = get_yclients_api()
        
        try:
            # Вызываем _request напрямую чтобы получить полный ответ с seance_length
            endpoint = f"/book_times/{api.company_id}/{staff_id}/{date}"
            
            params = {}
            if yclients_service_id:
                # ✅ ИСПРАВЛЕНИЕ: YClients API ожидает service_ids (массив)
                params['service_ids'] = [yclients_service_id]
                logger.info(f"📋 Фильтрация по услуге YClients ID: {yclients_service_id}")
            
            logger.info(f"📡 Запрос к YClients: {endpoint}")
            logger.debug(f"   Параметры: {params}")
            
            response = api._request('GET', endpoint, params=params)
            
            if not response.get('success', False):
                logger.warning(f"⚠️ API вернул success=false: {response}")
                return JsonResponse({
                    'success': True,
                    'data': {
                        'times': [],
                        'count': 0,
                        'date': date,
                        'staff_id': staff_id,
                        'warning': 'YClients API вернул success=false'
                    }
                })
            
            # Получаем данные
            data = response.get('data', [])
            
            logger.info(f"📦 YClients вернул: {len(data)} слотов")
            
            # ✅ ФИЛЬТРАЦИЯ ПО seance_length
            all_times = []
            filtered_times = []
            
            if isinstance(data, list):
                for slot in data:
                    if isinstance(slot, dict):
                        time_str = slot.get('time')
                        seance_length = slot.get('seance_length', 0)
                        
                        if time_str:
                            all_times.append(time_str)
                            
                            # Если указана длительность - фильтруем
                            if duration_minutes:
                                required_seconds = duration_minutes * 60
                                
                                if seance_length >= required_seconds:
                                    filtered_times.append(time_str)
                                    logger.debug(
                                        f"   ✅ {time_str}: доступно {seance_length//60} мин >= {duration_minutes} мин"
                                    )
                                else:
                                    logger.debug(
                                        f"   ❌ {time_str}: доступно {seance_length//60} мин < {duration_minutes} мин"
                                    )
                            else:
                                # Без фильтрации - добавляем все
                                filtered_times.append(time_str)
                    
                    elif isinstance(slot, str):
                        # Старый формат - просто строки
                        all_times.append(slot)
                        filtered_times.append(slot)
            
            # Определяем какой список возвращать
            result_times = filtered_times if duration_minutes else all_times
            was_filtered = duration_minutes is not None
            
            logger.info(
                f"✅ Результат: {len(result_times)} слотов "
                f"({'после фильтрации' if was_filtered else 'без фильтрации'})"
            )
            
            if was_filtered and len(all_times) > len(result_times):
                logger.info(
                    f"   Убрано слотов: {len(all_times) - len(result_times)} "
                    f"(не хватает времени для процедуры)"
                )
            
            # Формируем ответ
            response_data = {
                'times': result_times,
                'count': len(result_times),
                'date': date,
                'staff_id': staff_id,
                'filtered': was_filtered
            }
            
            # Добавляем доп. информацию если была фильтрация
            if was_filtered:
                response_data['duration_minutes'] = duration_minutes
                response_data['original_count'] = len(all_times)
                response_data['removed_count'] = len(all_times) - len(result_times)
            
            return JsonResponse({
                'success': True,
                'data': response_data
            })
            
        except YClientsAPIError as e:
            logger.error(f"❌ YClients API error: {e}")
            return JsonResponse({
                'success': True,
                'data': {
                    'times': [],
                    'count': 0,
                    'date': date,
                    'staff_id': staff_id,
                    'warning': f'Ошибка YClients API: {str(e)}'
                }
            })
            
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        
        return JsonResponse({
            'success': False,
            'error': 'Internal server error'
        }, status=500)


# ============================================================================
# АЛЬТЕРНАТИВА: Если хочешь сохранить старую функцию get_available_times
# ============================================================================

def api_available_times_simple(request):
    """
    Упрощённая версия - использует существующий метод get_available_times
    и фильтрует результат отдельной функцией
    """
    try:
        from services_app.yclients_api import get_yclients_api, YClientsAPIError
        from services_app.models import ServiceOption
        
        staff_id = request.GET.get('staff_id')
        date = request.GET.get('date')
        service_option_id = request.GET.get('service_option_id')
        
        if not staff_id or not date:
            return JsonResponse({
                'success': False,
                'error': 'staff_id and date are required'
            }, status=400)
        
        logger.info(f"⏰ Запрос доступных времён: {staff_id}, {date}")
        
        api = get_yclients_api()
        
        # Получаем ВСЕ доступные слоты
        times = api.get_available_times(
            staff_id=int(staff_id),
            date=date
        )
        
        # Если нужна фильтрация - делаем её здесь
        if service_option_id:
            try:
                option = ServiceOption.objects.get(id=service_option_id, is_active=True)
                
                # ⚠️ ПРОБЛЕМА: у нас нет seance_length в простом списке строк!
                # Нужно либо менять get_available_times, либо делать второй запрос
                
                logger.warning(
                    "⚠️ Фильтрация по длительности недоступна в упрощённой версии. "
                    "Используйте полную версию api_available_times выше."
                )
                
            except ServiceOption.DoesNotExist:
                pass
        
        return JsonResponse({
            'success': True,
            'data': {
                'times': times,
                'count': len(times),
                'date': date,
                'staff_id': staff_id
            }
        })
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Internal server error'
        }, status=500)
@csrf_exempt
@ratelimit(key="ip", rate="5/m", method="POST", block=True)
@require_POST
def api_create_booking(request):
    """
    API endpoint: создать запись клиента
    
    POST /api/booking/create/
    
    Body:
    {
        "staff_id": 4416525,
        "service_ids": [10461107, 10461108],  // ID услуг из YClients
        "date": "2025-12-15",
        "time": "10:00",
        "client": {
            "name": "Иван Петров",
            "phone": "79001234567",
            "email": "ivan@example.com"
        },
        "comment": "Комментарий"
    }
    """
    try:
        from services_app.yclients_api import get_yclients_api, YClientsAPIError
        from datetime import datetime
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Парсим JSON
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid JSON'
            }, status=400)
        
        # Валидация
        required = ['staff_id', 'service_ids', 'date', 'time', 'client']
        missing = [f for f in required if f not in body]
        if missing:
            return JsonResponse({
                'success': False,
                'error': f'Missing: {", ".join(missing)}'
            }, status=400)
        
        staff_id = body['staff_id']
        service_ids = body['service_ids']  # Массив ID услуг
        date = body['date']
        time = body['time']
        client = body['client']
        comment = body.get('comment', '')
        
        # Валидация client
        if not isinstance(client, dict):
            return JsonResponse({
                'success': False,
                'error': 'client must be object'
            }, status=400)
        
        if 'name' not in client or 'phone' not in client:
            return JsonResponse({
                'success': False,
                'error': 'client must have name and phone'
            }, status=400)

        # Нормализация телефона до +7XXXXXXXXXX перед записью в YClients
        try:
            client['phone'] = normalize_ru_phone(client.get('phone', ''))
        except ValidationError as exc:
            return JsonResponse({
                'success': False,
                'error': str(exc.message if hasattr(exc, 'message') else exc),
            }, status=400)
        
        # Валидация service_ids
        if not isinstance(service_ids, list) or not service_ids:
            return JsonResponse({
                'success': False,
                'error': 'service_ids must be non-empty array'
            }, status=400)
        
        # Валидация формата даты
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid date format. Use YYYY-MM-DD'
            }, status=400)
        
        # Валидация формата времени
        try:
            datetime.strptime(time, '%H:%M')
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid time format. Use HH:MM'
            }, status=400)
        
        # Формируем datetime
        booking_datetime = f"{date}T{time}:00"

        # Idempotency: если тот же клиент с тем же слотом уже пролетал
        # сквозь этот хэндлер за последние BOOKING_IDEMPOTENCY_TTL секунд,
        # возвращаем сохранённый ответ и НЕ трогаем YClients повторно.
        idem_key = _booking_idempotency_key(
            "create",
            client['phone'],
            staff_id,
            ",".join(str(s) for s in sorted(service_ids)),
            booking_datetime,
        )
        cached_response = cache.get(idem_key)
        if cached_response is not None:
            logger.info("api_create_booking: idempotent hit %s", idem_key[-16:])
            return JsonResponse(cached_response)

        # API клиент
        api = get_yclients_api()

        # Информация о мастере
        staff_list = api.get_staff()
        master = next((s for s in staff_list if s['id'] == staff_id), None)

        if not master:
            return JsonResponse({
                'success': False,
                'error': f'Staff {staff_id} not found'
            }, status=404)

        logger.info(
            f"📝 Создание записи: "
            f"staff={master['name']}, "
            f"datetime={booking_datetime}, "
            f"client={client['name']}, "
            f"services={service_ids}"
        )

        # Создаём запись
        booking = api.create_booking(
            staff_id=staff_id,
            services=service_ids,  # Передаём как есть
            datetime=booking_datetime,
            client=client,
            comment=comment
        )
        
        logger.info(
            f"✅ Запись создана! "
            f"Record ID: {booking.get('record_id')}"
        )
        
        response_payload = {
            'success': True,
            'data': {
                'booking_id': booking.get('record_id'),
                'booking_hash': booking.get('record_hash'),
                'staff_id': staff_id,
                'staff_name': master.get('name'),
                'datetime': booking_datetime,
                'service_ids': service_ids,
                'client_name': client['name'],
                'comment': comment
            }
        }
        # Кэшируем только успешный ответ. Ошибки YClients не кэшируем —
        # клиент должен иметь возможность немедленно повторить.
        cache.set(idem_key, response_payload, BOOKING_IDEMPOTENCY_TTL)
        return JsonResponse(response_payload)

    except YClientsAPIError as e:
        logger.exception(f"❌ YClients API Error: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
    except Exception as e:
        logger.exception(f"❌ Error: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

def category_services_by_slug(request, slug):
    """ЧПУ-версия страницы категории: /kategorii/<slug>/."""
    category = get_object_or_404(ServiceCategory, slug=slug)
    return _render_category_services(request, category)


def category_services(request, category_id):
    """Legacy-роут /services/<int:id>/. 301 на ЧПУ если есть slug."""
    category = get_object_or_404(ServiceCategory, pk=category_id)
    if category.slug:
        from django.shortcuts import redirect
        return redirect("website:category_services_by_slug", slug=category.slug, permanent=True)
    return _render_category_services(request, category)


def _render_category_services(request, category):
    """Общая логика рендера страницы категории (услуги + другие категории)."""
    services_qs = category.services.active().prefetch_related("options")

    other_categories = (
        ServiceCategory.objects
        .exclude(pk=category.pk)
        .prefetch_related("services")
        .order_by("order", "name")
    )

    return render(request, "website/category_services.html", {
        "settings": _settings(),
        "category": category,
        "services": services_qs,
        "other_categories": other_categories,
    })

def service_detail_by_slug(request, slug):
    """
    ЧПУ-версия страницы услуги: /uslugi/klassicheskij-massazh/
    Находит услугу по slug и вызывает основную логику.
    """
    service = get_object_or_404(
        Service.objects.select_related('category'),
        slug=slug,
        is_active=True
    )
    # Перенаправляем на основную логику по ID
    # (чтобы не дублировать код)
    return _render_service_detail(request, service)
    
def service_detail(request, service_id):
    """
    Страница конкретной услуги (по ID).
    Если у услуги есть slug — делаем 301 редирект на ЧПУ-URL.
    """
    service = get_object_or_404(
        Service.objects.select_related('category'),
        pk=service_id,
        is_active=True
    )
    
    # Если есть slug — редирект на ЧПУ
    if service.slug:
        from django.shortcuts import redirect
        return redirect('website:service_detail_by_slug', slug=service.slug, permanent=True)
    
    return _render_service_detail(request, service)

def _render_service_detail(request, service):

    # 2. Варианты услуги (только с yclients_service_id)
    options = service.options.filter(
        is_active=True
    ).exclude(
        yclients_service_id__isnull=True
    ).exclude(
        yclients_service_id=''
    ).order_by('order', 'duration_min', 'units')
    
    options_list = list(options)
    
    # 3. Уникальные длительности и количества
    durations = sorted(set(opt.duration_min for opt in options_list))
    quantities = set(opt.units for opt in options_list)
    
    # 4. Проверяем: одинаковое ли количество для ВСЕХ длительностей
    all_qty_pairs = set((opt.units, opt.get_unit_type_display()) for opt in options_list)
    is_single_quantity = len(all_qty_pairs) == 1
    single_qty_value = None
    single_qty_display = None
    if is_single_quantity and all_qty_pairs:
        single_qty_value, single_qty_display = all_qty_pairs.pop()
    
    # 5. Другие категории
    other_categories = ServiceCategory.objects.exclude(
        pk=service.category_id
    ).exclude(
        image__isnull=True
    ).exclude(
        image_mobile__isnull=True
    ).exclude(
        slug__isnull=True
    ).exclude(
        slug=''
    ).exclude(
        image=''
    ).order_by('order')

    # 6. Контентные блоки (SEO-лендинг)
    blocks = service.blocks.filter(is_active=True).order_by('order')

    media_items = list(service.media.filter(is_active=True).order_by('order'))
    
    carousels = {}
    single_media = []
    for m in media_items:
        if m.display_mode == 'carousel' and m.carousel_group:
            carousels.setdefault(m.carousel_group, []).append(m)
        else:
            single_media.append(m)

    media_by_position = {}
    for m in single_media:
        media_by_position.setdefault(m.insert_after_order, []).append(
            {'type': 'single', 'item': m}
        )
    for group_name, items in carousels.items():
        pos = items[0].insert_after_order
        media_by_position.setdefault(pos, []).append(
            {'type': 'carousel', 'group': group_name, 'items': items}
        )
    
    logger.info(f"Других категорий с фото: {other_categories.count()}")
    
    # 7. SEO — fallback на название услуги если поля пусты
    _price_str = f" — от {int(service.price_from)} ₽" if service.price_from else ''
    _raw_title = service.seo_title or f"{service.name}{_price_str} | Пенза"
    # Обрезаем title до 65 символов по последнему пробелу
    seo_title = _raw_title[:65].rsplit(' ', 1)[0] if len(_raw_title) > 65 else _raw_title
    # description: убираем переносы строк из автофолбека, обрезаем до 160
    if service.seo_description:
        seo_description = service.seo_description
    elif service.description:
        _clean = service.description.replace('\n', ' ').replace('\r', ' ').strip()
        seo_description = (_clean[:157].rsplit(' ', 1)[0] + '...') if len(_clean) > 160 else _clean
    else:
        seo_description = ""
    seo_h1 = service.seo_h1 or service.name
    
    related_services = (
        service.related_services.active()
        .with_category()
        .prefetch_related('options')
        .order_by('order')
    )

    related_with_prices = []
    for rs in related_services:
        min_price = None
        active_options = rs.options.filter(is_active=True).exclude(
            yclients_service_id__isnull=True
        ).exclude(yclients_service_id='')
        if active_options.exists():
            min_price = active_options.order_by('price').first().price
        related_with_prices.append({
            'service': rs,
            'min_price': min_price,
        })

    context = {
        'service': service,
        'options': options_list,
        'options_count': len(options_list),
        'durations': durations,
        'durations_count': len(durations),
        'quantities_count': len(quantities),
        'is_single_quantity_for_all_durations': is_single_quantity,
        'single_quantity_value': single_qty_value,
        'single_quantity_unit_type_display': single_qty_display,
        'other_categories': other_categories,
        'settings': SiteSettings.objects.first(),
        # SEO
        'seo_title': seo_title,
        'seo_description': seo_description,
        'seo_h1': seo_h1,
        'subtitle': service.subtitle,
        # Контентные блоки
        'blocks': blocks,
        'has_blocks': blocks.exists(),

        'media_items': media_items,
        'media_by_position': media_by_position,
        'carousels': carousels,
        'has_media': len(media_items) > 0,

        'related_services': related_with_prices,
        'has_related': len(related_with_prices) > 0,
    }
    
    return render(request, 'website/service_detail.html', context)

@require_GET
def api_service_options(request):
    """
    API: Получить опции (варианты) конкретной услуги.
    GET /api/booking/service_options/?service_id=123
    
    Возвращает список опций с длительностью, количеством, ценой.
    Используется модалкой бронирования на странице «Услуги».
    """
    service_id = request.GET.get('service_id')
    
    if not service_id:
        return JsonResponse({
            'success': False,
            'error': 'service_id обязателен'
        }, status=400)
    
    try:
        service = Service.objects.get(id=service_id, is_active=True)
    except Service.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Услуга не найдена'
        }, status=404)
    
    options = ServiceOption.objects.active().for_service(service).ordered()
    
    data = []
    for opt in options:
        data.append({
            'id': opt.id,
            'duration': opt.duration_min,
            'quantity': opt.units,
            'unit_type': opt.unit_type,
            'unit_type_display': opt.get_unit_type_display(),
            'price': float(opt.price),
            'yclients_id': opt.yclients_service_id or '',
        })
    
    return JsonResponse({
        'success': True,
        'data': data,
        'service_name': service.name,
    })


# Добавить в website/urls.py (в urlpatterns):
# path('api/booking/service_options/', views.api_service_options, name='api_service_options'),

"""  
def _get_other_services(service, limit=8):

    other = []
    
    if service.category:
        # Услуги из той же категории
        other = list(
            Service.objects
            .filter(category=service.category, is_active=True)
            .exclude(pk=service.pk)
            .order_by('-is_popular', 'name')
            [:limit]
        )
        
        # Добавляем популярные, если мало
        if len(other) < limit:
            popular = list(
                Service.objects
                .filter(is_active=True, is_popular=True)
                .exclude(pk=service.pk)
                .exclude(category=service.category)
                [:limit - len(other)]
            )
            other.extend(popular)
    else:
        # Без категории — только популярные
        other = list(
            Service.objects
            .filter(is_active=True, is_popular=True)
            .exclude(pk=service.pk)
            .order_by('name')
            [:limit]
        )
    
    return other
"""

@csrf_exempt
@ratelimit(key="ip", rate="30/m", method="GET", block=True)
def api_available_dates(request):
    """
    API: получить список доступных дат для мастера.
    
    GET /api/booking/available_dates/?staff_id=4416525
    """
    try:
        from services_app.yclients_api import get_yclients_api, YClientsAPIError
        import logging
        
        logger = logging.getLogger(__name__)
        
        staff_id = request.GET.get('staff_id')
        
        if not staff_id:
            return JsonResponse({
                'success': False,
                'error': 'staff_id is required'
            }, status=400)
        
        logger.info(f"📅 Запрос доступных дат для мастера: {staff_id}")
        
        api = get_yclients_api()
        
        # Получаем доступные даты
        dates = api.get_book_dates(staff_id=int(staff_id))
        
        logger.info(f"✅ Найдено доступных дат: {len(dates)}")
        logger.debug(f"Dates: {dates}")
        
        # Если дат нет - возвращаем пустой массив, но success=true
        return JsonResponse({
            'success': True,
            'data': {
                'dates': dates,
                'count': len(dates)
            }
        })
        
    except YClientsAPIError as e:
        logger.error(f"❌ YClients API error: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
    except Exception as e:
        logger.error(f"❌ Unexpected error in api_available_dates: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JsonResponse({
            'success': False,
            'error': 'Internal server error'
        }, status=500)
        
@csrf_exempt
@ratelimit(key="ip", rate="30/m", method="GET", block=True)
@require_GET
def api_get_staff(request):
    """
    API: Получить список мастеров для услуги
    GET /api/booking/get_staff/?service_option_id=123
    
    Если service_option_id указан, возвращает только мастеров, которые могут оказывать эту услугу.
    Если не указан, возвращает всех активных мастеров.
    """
    from services_app.yclients_api import get_yclients_api
    from services_app.models import ServiceOption
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        service_option_id = request.GET.get('service_option_id')

        if service_option_id:
            # Фильтрация по услуге через YClients API
            try:
                option = ServiceOption.objects.get(
                    id=int(service_option_id),
                    is_active=True
                )

                if not option.yclients_service_id:
                    # Услуга без YClients ID - возвращаем пустой список
                    logger.warning(f"⚠️ У ServiceOption {service_option_id} нет yclients_service_id")
                    return JsonResponse({
                        'success': True,
                        'data': [],
                        'count': 0,
                        'message': 'Услуга не привязана к YClients'
                    })

                # ✅ ИСПОЛЬЗУЕМ YCLIENTS API С ФИЛЬТРАЦИЕЙ ПО УСЛУГЕ
                logger.info(f"🔍 Загружаем мастеров для услуги '{option.service.name}' (yclients_service_id={option.yclients_service_id})")

                # Преобразуем yclients_service_id в int (может быть строкой)
                try:
                    service_id_int = int(option.yclients_service_id)
                except (ValueError, TypeError):
                    logger.error(f"❌ Некорректный yclients_service_id: {option.yclients_service_id}")
                    return JsonResponse({
                        'success': False,
                        'error': f'Некорректный ID услуги в YClients: {option.yclients_service_id}'
                    }, status=400)

                # Инициализируем API только здесь, когда он действительно нужен
                api = get_yclients_api()

                # Получаем мастеров, которые могут оказывать эту услугу
                staff_list = api.get_staff(service_id=service_id_int)
                logger.info(f"✅ YClients вернул {len(staff_list)} мастеров для услуги {service_id_int}")
                
                # Форматируем ответ
                formatted_staff = []
                for staff in staff_list:
                    formatted_staff.append({
                        'id': staff.get('id'),
                        'name': staff.get('name', ''),
                        'specialization': staff.get('specialization', ''),
                        'avatar': staff.get('avatar', ''),
                        'rating': staff.get('rating', 0),
                    })
                
                return JsonResponse({
                    'success': True,
                    'data': formatted_staff,
                    'count': len(formatted_staff)
                })
                    
            except ServiceOption.DoesNotExist:
                logger.error(f"❌ ServiceOption {service_option_id} не найден")
                return JsonResponse({
                    'success': False,
                    'error': f'Вариант услуги {service_option_id} не найден'
                }, status=404)
            except ValueError:
                logger.error(f"❌ Некорректный service_option_id: {service_option_id}")
                return JsonResponse({
                    'success': False,
                    'error': 'Некорректный ID варианта услуги'
                }, status=400)
        else:
            # Без фильтра - возвращаем пустой список (не загружаем всех мастеров)
            # Это предотвращает показ всех мастеров при загрузке страницы
            logger.info("📋 Запрос мастеров без service_option_id - возвращаем пустой список")
            return JsonResponse({
                'success': True,
                'data': [],
                'count': 0,
                'message': 'Укажите service_option_id для получения мастеров'
            })
        
    except Exception as e:
        logger.exception(f"❌ Ошибка api_get_staff: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@ratelimit(key="ip", rate="5/m", method="POST", block=True)
@require_POST
def api_bundle_request(request):
    """API: Заявка на комплекс — сохранение + уведомления."""
    import json
    from services_app.models import Bundle, BundleRequest
    from website.notifications import send_notification_telegram, send_notification_email

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    name = data.get('name', '').strip()
    raw_phone = data.get('phone', '').strip()
    email = data.get('email', '').strip()
    comment = data.get('comment', '').strip()
    bundle_id = data.get('bundle_id')
    bundle_name = data.get('bundle_name', '')

    if not name or not raw_phone:
        return JsonResponse({'success': False, 'error': 'Имя и телефон обязательны'}, status=400)

    try:
        phone = normalize_ru_phone(raw_phone)
    except ValidationError as exc:
        return JsonResponse({'success': False, 'error': str(exc.message if hasattr(exc, 'message') else exc)}, status=400)

    # Idempotency: тот же клиент на тот же bundle с тем же комментарием
    # не должен плодить дубли BundleRequest при дабл-клике / retry.
    idem_key = _booking_idempotency_key(
        "bundle", phone, bundle_id or "", comment[:64]
    )
    cached_response = cache.get(idem_key)
    if cached_response is not None:
        logger.info("api_bundle_request: idempotent hit %s", idem_key[-16:])
        return JsonResponse(cached_response)

    bundle = None
    if bundle_id:
        try:
            bundle = Bundle.objects.get(id=bundle_id)
            bundle_name = bundle.name
        except Bundle.DoesNotExist:
            pass

    req = BundleRequest.objects.create(
        bundle=bundle,
        bundle_name=bundle_name,
        client_name=name,
        client_phone=phone,
        client_email=email,
        comment=comment,
    )

    tg_text = (
        f"🔔 Новая заявка на комплекс!\n\n"
        f"📦 {bundle_name}\n"
        f"👤 {name}\n"
        f"📱 {phone}\n"
    )
    if email:
        tg_text += f"📧 {email}\n"
    if comment:
        tg_text += f"💬 {comment}\n"
    send_notification_telegram(tg_text)

    send_notification_email(
        subject=f"Заявка на комплекс: {bundle_name}",
        message=(
            f"Комплекс: {bundle_name}\n"
            f"Клиент:   {name}\n"
            f"Телефон:  {phone}\n"
            f"Email:    {email or '—'}\n"
            f"Комментарий: {comment or '—'}\n"
        ),
    )

    response_payload = {
        'success': True,
        'message': 'Заявка принята! Администратор свяжется с вами.',
    }
    cache.set(idem_key, response_payload, BOOKING_IDEMPOTENCY_TTL)
    return JsonResponse(response_payload)

@require_GET
def api_wizard_categories(request):
    """Список категорий с количеством активных услуг"""
    categories = ServiceCategory.objects.prefetch_related("services").order_by("order", "name")
    result = []
    for cat in categories:
        active_count = cat.services.active().count()
        if active_count > 0:
            result.append({
                "id": cat.id,
                "name": cat.name,
                "services_count": active_count,
            })
    return JsonResponse({"categories": result})

@require_GET
def api_wizard_services(request, category_id):
    """Услуги категории с первым вариантом (цена, длительность)"""
    services = (
        Service.objects.active()
        .filter(category_id=category_id)
        .prefetch_related("options")
        .order_by("name")
    )

    result = []
    for svc in services:
        first_opt = svc.options.active().order_by("order", "price").first()
        result.append({
            "id": svc.id,
            "name": svc.name,
            "duration": first_opt.duration_min if first_opt else None,
            "price": int(first_opt.price) if first_opt and first_opt.price else None,
            "option_id": first_opt.id if first_opt else None,
        })
    return JsonResponse({"services": result})

@csrf_exempt
@ratelimit(key="ip", rate="5/m", method="POST", block=True)
@require_POST
def api_wizard_booking(request):
    """Заявка с формы-мастера (#bookingWizard / кнопка «Записаться онлайн»).

    By design НЕ создаёт запись в YClients — это «заявка на перезвон».
    Менеджер обрабатывает вручную по уведомлению в Telegram/email.

    Сохраняет BookingRequest в БД и шлёт два уведомления:
      - Telegram: _send_booking_telegram
      - Email:    _send_booking_email (список получателей — в SiteSettings.notification_emails)
    """
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Неверный формат данных"}, status=400)

    client_name = data.get("client_name", "").strip()
    raw_phone = data.get("client_phone", "").strip()
    comment = data.get("comment", "").strip()
    service_id = data.get("service_id")

    if not client_name or not raw_phone:
        return JsonResponse({"success": False, "error": "Укажите имя и телефон"}, status=400)

    try:
        client_phone = normalize_ru_phone(raw_phone)
    except ValidationError as exc:
        return JsonResponse({"success": False, "error": str(exc.message if hasattr(exc, 'message') else exc)}, status=400)

    # Idempotency-ключ: телефон + услуга + обрезанный комментарий.
    # Защищает от дубликатов BookingRequest при double-submit.
    idem_key = _booking_idempotency_key(
        "wizard", client_phone, service_id or "", comment[:64]
    )
    cached_response = cache.get(idem_key)
    if cached_response is not None:
        logger.info("api_wizard_booking: idempotent hit %s", idem_key[-16:])
        return JsonResponse(cached_response)

    # Получаем названия
    service_name = "Не указана"
    category_name = ""
    if service_id:
        try:
            svc = Service.objects.select_related("category").get(id=service_id)
            service_name = svc.name
            category_name = svc.category.name if svc.category else ""
        except Service.DoesNotExist:
            pass

    # Сохраняем в БД
    booking = BookingRequest.objects.create(
        category_name=category_name,
        service_name=service_name,
        client_name=client_name,
        client_phone=client_phone,
        comment=comment,
    )

    # Уведомления: Telegram + email (список адресов в SiteSettings.notification_emails)
    _notify_booking_request(booking)

    response_payload = {"success": True, "id": booking.id}
    cache.set(idem_key, response_payload, BOOKING_IDEMPOTENCY_TTL)
    return JsonResponse(response_payload)


def _notify_booking_request(booking):
    """Шлёт Telegram и email о новой заявке с формы-мастера (wizard)."""
    from website.notifications import send_notification_telegram, send_notification_email

    tg_text = (
        f"📋 Новая заявка с сайта!\n\n"
        f"👤 {booking.client_name}\n"
        f"📞 {booking.client_phone}\n"
        f"💆 {booking.service_name}\n"
    )
    if booking.category_name:
        tg_text += f"📂 {booking.category_name}\n"
    if booking.comment:
        tg_text += f"💬 {booking.comment}\n"
    send_notification_telegram(tg_text)

    email_lines = [
        f"Категория: {booking.category_name or '—'}",
        f"Услуга:    {booking.service_name}",
        f"Клиент:    {booking.client_name}",
        f"Телефон:   {booking.client_phone}",
    ]
    if booking.comment:
        email_lines.append(f"Комментарий: {booking.comment}")
    email_lines.append(f"Время заявки: {booking.created_at:%d.%m.%Y %H:%M}")
    email_lines.append("")
    email_lines.append("Админка: /admin/services_app/bookingrequest/")

    send_notification_email(
        subject=f"Новая заявка с сайта: {booking.service_name}",
        message="\n".join(email_lines),
    )


# ── Сертификаты ───────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


def certificates(request):
    """Страница подарочных сертификатов"""
    popular_services = (
        Service.objects.active().popular()
        .prefetch_related("options")
        .order_by("order")[:8]
    )
    return render(request, "website/certificates.html", {
        "popular_services": popular_services,
    })


@ratelimit(key="ip", rate="5/m", method="POST", block=True)
@require_POST
def api_certificate_request(request):
    """API: Заявка на подарочный сертификат."""
    from datetime import date, timedelta

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    # --- Валидация ---
    buyer_name = data.get("buyer_name", "").strip()
    raw_buyer_phone = data.get("buyer_phone", "").strip()
    if not buyer_name or not raw_buyer_phone:
        return JsonResponse(
            {"success": False, "error": "Имя и телефон покупателя обязательны"},
            status=400,
        )

    try:
        buyer_phone = normalize_ru_phone(raw_buyer_phone)
    except ValidationError as exc:
        return JsonResponse(
            {"success": False, "error": str(exc.message if hasattr(exc, 'message') else exc)},
            status=400,
        )

    cert_type = data.get("certificate_type", "nominal")
    if cert_type not in ("nominal", "service"):
        return JsonResponse(
            {"success": False, "error": "Неверный тип сертификата"},
            status=400,
        )

    nominal = 0
    service = None
    service_option = None

    if cert_type == "nominal":
        try:
            nominal = int(data.get("nominal", 0))
        except (TypeError, ValueError):
            nominal = 0
        if nominal <= 0:
            return JsonResponse(
                {"success": False, "error": "Укажите сумму сертификата"},
                status=400,
            )
    else:
        service_id = data.get("service_id")
        if not service_id:
            return JsonResponse(
                {"success": False, "error": "Выберите услугу"},
                status=400,
            )
        try:
            service = Service.objects.get(id=service_id, is_active=True)
        except Service.DoesNotExist:
            return JsonResponse(
                {"success": False, "error": "Услуга не найдена"},
                status=404,
            )
        option_id = data.get("service_option_id")
        if option_id:
            try:
                service_option = ServiceOption.objects.get(
                    id=option_id, service=service, is_active=True,
                )
                nominal = service_option.price
            except ServiceOption.DoesNotExist:
                pass
        if not nominal and service.price_from:
            nominal = service.price_from

    buyer_email = data.get("buyer_email", "").strip()
    recipient_name = data.get("recipient_name", "").strip()
    raw_recipient_phone = data.get("recipient_phone", "").strip()
    message = data.get("message", "").strip()

    recipient_phone = ""
    if raw_recipient_phone:
        try:
            recipient_phone = normalize_ru_phone(raw_recipient_phone)
        except ValidationError as exc:
            return JsonResponse(
                {"success": False, "error": f"Телефон получателя: {exc.message if hasattr(exc, 'message') else exc}"},
                status=400,
            )

    payment_method = data.get("payment_method", "cash")
    if payment_method not in ("online", "cash"):
        payment_method = "cash"

    # --- Онлайн-оплата: проверка feature flag ---
    site = SiteSettings.objects.first()
    if payment_method == "online":
        if not site or not site.online_payment_enabled:
            return JsonResponse({"success": False, "error": "online_payment_disabled"}, status=400)

    # --- Создание Order ---
    order = Order.objects.create(
        order_type="certificate",
        payment_method=payment_method,
        payment_status="pending" if payment_method == "online" else "not_required",
        client_name=buyer_name,
        client_phone=buyer_phone,
        client_email=buyer_email,
        total_amount=nominal,
        comment=message,
    )

    # --- Создание GiftCertificate ---
    today = date.today()
    cert = GiftCertificate.objects.create(
        order=order,
        certificate_type=cert_type,
        nominal=nominal,
        service=service,
        service_option=service_option,
        buyer_name=buyer_name,
        buyer_phone=buyer_phone,
        buyer_email=buyer_email,
        recipient_name=recipient_name,
        recipient_phone=recipient_phone,
        message=message,
        valid_from=today,
        valid_until=today + timedelta(days=180),
    )

    # --- Онлайн: создать платёж YooKassa, вернуть payment_url ---
    if payment_method == "online":
        from payments.exceptions import PaymentError
        from payments.services import PaymentService
        try:
            payment_url = PaymentService().create_for_order(order)
        except PaymentError as exc:
            logger.error("api_certificate_request: PaymentService failed: %s", exc)
            return JsonResponse({"success": False, "error": "payment_create_failed"}, status=502)
        return JsonResponse({
            "success": True,
            "order_number": order.number,
            "payment_method": "online",
            "payment_url": payment_url,
        })

    # --- Офлайн: уведомления администраторам ---
    from website.notifications import send_notification_email, send_notification_telegram

    value_str = (
        f"{nominal:,.0f} ₽".replace(",", " ")
        if cert_type == "nominal"
        else str(service)
    )
    tg_text = (
        f"🎁 Новая заявка на сертификат!\n\n"
        f"💰 {value_str}\n"
        f"👤 {buyer_name}, {buyer_phone}\n"
    )
    if recipient_name:
        tg_text += f"🎀 Получатель: {recipient_name}\n"
    if recipient_phone:
        tg_text += f"📱 {recipient_phone}\n"
    if message:
        tg_text += f"💬 {message}\n"
    tg_text += f"\n№ заказа: {order.number}"
    send_notification_telegram(tg_text)

    send_notification_email(
        subject=f"Заявка на сертификат: {order.number}",
        message=(
            f"Покупатель: {buyer_name}, {buyer_phone}\n"
            f"Получатель: {recipient_name or '—'}\n"
            f"Тип: {cert.get_certificate_type_display()}\n"
            f"Номинал: {nominal}\n"
            f"№ заказа: {order.number}\n"
        ),
    )

    return JsonResponse({
        "success": True,
        "message": "Заявка принята! Менеджер свяжется с вами для оплаты.",
        "order_number": order.number,
    })


@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="10/m", method="POST", block=True)
def api_service_order_create(request):
    """POST /api/services/order/ — оформление заказа на услугу.

    Единая точка входа для 3 способов оплаты (online/cash/card_offline):
    - Валидация payload через ServiceOrderCreateSerializer
    - Создаёт Order(type="service") с нормализованным телефоном
    - payment_method=online + SiteSettings.online_payment_enabled → создаёт
      YooKassa-платёж через PaymentService, возвращает payment_url для редиректа.
    - payment_method=cash/card_offline → создаёт запись в YClients сразу
      через YClientsBookingService, возвращает yclients_record_id.
    - Idempotency через кэш: двойной submit за 60с возвращает тот же ответ.
    """
    from website.serializers import ServiceOrderCreateSerializer
    from payments.booking_service import YClientsBookingService
    from payments.exceptions import (
        BookingClientError,
        BookingValidationError,
        PaymentConfigError,
        PaymentError,
    )
    from payments.services import PaymentService
    from website.notifications import send_notification_telegram

    logger = logging.getLogger(__name__)

    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "invalid json"}, status=400)

    serializer = ServiceOrderCreateSerializer(data=body)
    if not serializer.is_valid():
        return JsonResponse(
            {"success": False, "error": "validation", "errors": serializer.errors},
            status=400,
        )
    data = serializer.validated_data
    payment_method = data["payment_method"]
    option: ServiceOption = data["service_option"]

    # Feature flag: online недоступен пока YooKassa не настроена
    if payment_method == "online":
        site = _settings()
        if not site or not site.online_payment_enabled:
            return JsonResponse(
                {"success": False, "error": "online_payment_disabled"},
                status=400,
            )

    # Idempotency (double-click, retry сетевого глитча)
    idem_key = _booking_idempotency_key(
        "service_order",
        data["client_phone"],
        data["staff_id"],
        data["service_option_id"],
        data["scheduled_at"].isoformat(),
        payment_method,
    )
    cached = cache.get(idem_key)
    if cached is not None:
        logger.info("api_service_order_create: idempotent hit %s", idem_key[-16:])
        return JsonResponse(cached)

    order = Order.objects.create(
        order_type="service",
        status="pending",
        payment_method=payment_method,
        payment_status="pending" if payment_method == "online" else "not_required",
        client_name=data["client_name"],
        client_phone=data["client_phone"],
        client_email=data.get("client_email", ""),
        total_amount=option.price,
        service=option.service,
        service_option=option,
        staff_id=data["staff_id"],
        scheduled_at=data["scheduled_at"],
        comment=data.get("comment", ""),
    )

    if payment_method == "online":
        try:
            payment_url = PaymentService().create_for_order(order)
        except PaymentConfigError:
            logger.error("api_service_order_create: YooKassa not configured")
            order.delete()
            return JsonResponse(
                {"success": False, "error": "online_payment_unavailable"},
                status=503,
            )
        except PaymentError as exc:
            logger.exception("api_service_order_create: PaymentService failed")
            order.delete()
            return JsonResponse(
                {"success": False, "error": "payment_create_failed", "detail": str(exc)},
                status=502,
            )
        response = {
            "success": True,
            "order_number": order.number,
            "payment_method": "online",
            "payment_url": payment_url,
        }
    else:
        # Offline: создаём YClients-запись сразу, клиент платит в салоне.
        try:
            result = YClientsBookingService().create_record(order)
        except (BookingValidationError, BookingClientError) as exc:
            logger.warning(
                "api_service_order_create: YClients failed for order=%s: %s",
                order.number, exc,
            )
            order.status = "cancelled"
            order.admin_note = f"create_booking failed: {exc}"
            order.save(update_fields=["status", "admin_note", "updated_at"])
            return JsonResponse(
                {"success": False, "error": "booking_failed", "detail": str(exc)},
                status=502,
            )
        # Оффлайн-оплата — уведомление админу что клиент зайдёт и оплатит на кассе.
        send_notification_telegram(
            f"📝 Новая запись (оплата в салоне): {order.number}\n"
            f"Клиент: {order.client_name} {order.client_phone}\n"
            f"Услуга: {option.service.name}\n"
            f"Мастер ID: {order.staff_id}, время: {order.scheduled_at:%d.%m.%Y %H:%M}\n"
            f"Способ оплаты: {order.get_payment_method_display()}\n"
            f"Сумма к оплате: {order.total_amount} ₽\n"
            f"YClients record: {result['record_id']}"
        )
        response = {
            "success": True,
            "order_number": order.number,
            "payment_method": payment_method,
            "yclients_record_id": result["record_id"],
            "message": "Запись подтверждена. Оплата — в салоне.",
        }

    cache.set(idem_key, response, BOOKING_IDEMPOTENCY_TTL)
    return JsonResponse(response)


@require_GET
def api_certificate_check(request):
    """API: \u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442\u0430 \u043f\u043e \u043a\u043e\u0434\u0443"""
    code = request.GET.get("code", "").strip().upper()
    if not code:
        return JsonResponse(
            {"success": False, "error": "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043a\u043e\u0434 \u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442\u0430"}, status=400,
        )
    try:
        cert = GiftCertificate.objects.select_related("service").get(code=code)
    except GiftCertificate.DoesNotExist:
        return JsonResponse(
            {"success": False, "error": "\u0421\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d"}, status=404,
        )

    remaining = cert.remaining_value
    return JsonResponse({
        "success": True,
        "certificate": {
            "code": cert.code,
            "type": cert.certificate_type,
            "type_display": cert.get_certificate_type_display(),
            "nominal": str(cert.nominal) if cert.certificate_type == "nominal" else None,
            "service_name": str(cert.service) if cert.service else None,
            "remaining_value": str(remaining) if remaining is not None else None,
            "status": cert.get_status_display(),
            "valid": cert.is_valid,
            "valid_until": cert.valid_until.isoformat(),
        },
    })
