from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from collections import defaultdict
from django.db.models import Prefetch
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from services_app.yclients_api import get_yclients_api, YClientsAPIError
import logging
import json
import requests as http_requests
from django.conf import settings as django_settings

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

    # Категории услуг для секции "Услуги салона"
    categories = (
        ServiceCategory.objects.prefetch_related("services")
        .filter(services__is_active=True)
        .distinct()
        .order_by("order", "name")[:8]
    )

    # Мастера для секции "Наши мастера"
    masters = Master.objects.filter(is_active=True).prefetch_related("services").all().order_by("name")[:4]

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

    # Отзывы для секции "Отзывы"
    reviews = Review.objects.filter(is_active=True).order_by("order", "-date", "-created_at")[:3]
    
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
    promos = (
        Promotion.objects.filter(is_active=True)
        .order_by("order", "-starts_at", "title")[:1]
    )
    
    return render(request, "website/services.html", {
        "settings": _settings(),
        "categories": categories,
        "promotions": promos,
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
    items = Master.objects.filter(is_active=True).prefetch_related(
        "services",
        "services__options",
    ).all().order_by("order", "name")
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
    
    # Лечебные комплексы — услуги с "комплекс" в названии
    complex_opt_qs = (ServiceOption.objects
                      .filter(is_active=True)
                      .order_by("order", "units", "duration_min"))
    complex_services = (Service.objects
                        .filter(is_active=True, name__icontains='комплекс')
                        .prefetch_related(Prefetch('options', queryset=complex_opt_qs))
                        .order_by('name'))

    return render(request, "website/bundles.html", {
        "settings": _settings(),
        "bundles": bundles,
        "complex_services": complex_services,
    })

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
        
        return JsonResponse({
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
        })
        
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

def category_services(request, category_id):
    """Услуги конкретной категории"""
    category = get_object_or_404(ServiceCategory, id=category_id)
    services_qs = (
        category.services
        .filter(is_active=True)
        .prefetch_related("options")
    )
    
    # Другие категории (исключаем текущую)
    other_categories = (
        ServiceCategory.objects
        .exclude(id=category_id)
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
    seo_title = service.seo_title or f"{service.name} — {service.category.name if service.category else ''}"
    seo_description = service.seo_description or (service.description[:160] if service.description else "")
    seo_h1 = service.seo_h1 or service.name
    
    related_services = service.related_services.filter(
        is_active=True
    ).select_related('category').prefetch_related('options').order_by('order')
    
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
    
    options = ServiceOption.objects.filter(
        service=service,
        is_active=True
    ).order_by('order', 'duration_min', 'unit_type', 'units')
    
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

@require_POST
def api_bundle_request(request):
    """API: Заявка на комплекс — сохранение + уведомление"""
    import json
    from services_app.models import Bundle, BundleRequest
    from django.core.mail import send_mail

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    email = data.get('email', '').strip()
    comment = data.get('comment', '').strip()
    bundle_id = data.get('bundle_id')
    bundle_name = data.get('bundle_name', '')

    if not name or not phone:
        return JsonResponse({'success': False, 'error': 'Имя и телефон обязательны'}, status=400)

    # Находим комплекс
    bundle = None
    if bundle_id:
        try:
            bundle = Bundle.objects.get(id=bundle_id)
            bundle_name = bundle.name
        except Bundle.DoesNotExist:
            pass

    # Сохраняем в БД
    req = BundleRequest.objects.create(
        bundle=bundle,
        bundle_name=bundle_name,
        client_name=name,
        client_phone=phone,
        client_email=email,
        comment=comment,
    )

    # Уведомление в Telegram
    tg_token = getattr(django_settings, 'TELEGRAM_BOT_TOKEN', '')
    tg_chat = getattr(django_settings, 'TELEGRAM_CHAT_ID', '')
    if tg_token and tg_chat:
        try:
            text = (
                f"🔔 Новая заявка на комплекс!\n\n"
                f"📦 {bundle_name}\n"
                f"👤 {name}\n"
                f"📱 {phone}\n"
            )
            if email:
                text += f"📧 {email}\n"
            if comment:
                text += f"💬 {comment}\n"

            http_requests.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                json={"chat_id": tg_chat, "text": text, "parse_mode": "HTML"},
                timeout=5
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Telegram notification failed: {e}")

    # Уведомление по Email
    admin_email = getattr(django_settings, 'ADMIN_NOTIFICATION_EMAIL', '')
    if admin_email:
        try:
            send_mail(
                subject=f"Заявка на комплекс: {bundle_name}",
                message=f"Имя: {name}\nТелефон: {phone}\nEmail: {email}\nКомментарий: {comment}",
                from_email=None,
                recipient_list=[admin_email],
                fail_silently=True,
            )
        except Exception:
            pass

    return JsonResponse({
        'success': True,
        'message': 'Заявка принята! Администратор свяжется с вами.'
    })

@require_GET
def api_wizard_categories(request):
    """Список категорий с количеством активных услуг"""
    categories = ServiceCategory.objects.prefetch_related("services").order_by("order", "name")
    result = []
    for cat in categories:
        active_count = cat.services.filter(is_active=True).count()
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
    services = Service.objects.filter(
        category_id=category_id, is_active=True
    ).prefetch_related("options").order_by("name")

    result = []
    for svc in services:
        first_opt = svc.options.filter(is_active=True).order_by("order", "price").first()
        result.append({
            "id": svc.id,
            "name": svc.name,
            "duration": first_opt.duration_min if first_opt else None,
            "price": int(first_opt.price) if first_opt and first_opt.price else None,
            "option_id": first_opt.id if first_opt else None,
        })
    return JsonResponse({"services": result})

@csrf_exempt
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
    client_phone = data.get("client_phone", "").strip()
    comment = data.get("comment", "").strip()
    service_id = data.get("service_id")

    if not client_name or not client_phone:
        return JsonResponse({"success": False, "error": "Укажите имя и телефон"}, status=400)

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
    _send_booking_telegram(booking)
    _send_booking_email(booking)

    return JsonResponse({"success": True, "id": booking.id})


def _send_booking_telegram(booking):
    """Отправка уведомления в Telegram"""
    from django.conf import settings as django_settings
    
    token = getattr(django_settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(django_settings, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return

    text = (
        f"📋 Новая заявка с сайта!\n\n"
        f"👤 {booking.client_name}\n"
        f"📞 {booking.client_phone}\n"
        f"💆 {booking.service_name}\n"
    )
    if booking.category_name:
        text += f"📂 {booking.category_name}\n"
    if booking.comment:
        text += f"💬 {booking.comment}\n"

    try:
        http_requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except Exception as e:
        logger.error(f"Telegram notification failed: {e}")


def _send_booking_email(booking):
    """Отправка заявки wizard на email администраторов.

    Список получателей берётся из SiteSettings.notification_emails
    (редактируется через Django Admin). Если там пусто — fallback
    на ADMIN_NOTIFICATION_EMAIL из окружения.
    """
    from django.conf import settings as django_settings
    from django.core.mail import send_mail
    from services_app.models import SiteSettings

    recipients: list[str] = []
    site = SiteSettings.objects.first()
    if site:
        recipients = site.get_notification_emails()

    if not recipients:
        fallback = getattr(django_settings, "ADMIN_NOTIFICATION_EMAIL", "")
        if fallback:
            recipients = [fallback]

    if not recipients:
        return

    subject = f"Новая заявка с сайта: {booking.service_name}"
    lines = [
        f"Категория: {booking.category_name or '—'}",
        f"Услуга:    {booking.service_name}",
        f"Клиент:    {booking.client_name}",
        f"Телефон:   {booking.client_phone}",
    ]
    if booking.comment:
        lines.append(f"Комментарий: {booking.comment}")
    lines.append(f"Время заявки: {booking.created_at:%d.%m.%Y %H:%M}")
    lines.append("")
    lines.append("Админка: /admin/services_app/bookingrequest/")

    try:
        send_mail(
            subject=subject,
            message="\n".join(lines),
            from_email=None,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception as e:
        logger.error(f"Booking email notification failed: {e}")


# ── Сертификаты ───────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


def certificates(request):
    """Страница подарочных сертификатов"""
    popular_services = (
        Service.objects
        .filter(is_active=True, is_popular=True)
        .prefetch_related("options")
        .order_by("order")[:8]
    )
    return render(request, "website/certificates.html", {
        "popular_services": popular_services,
    })


@require_POST
def api_certificate_request(request):
    """API: Заявка на подарочный сертификат"""
    from datetime import date, timedelta
    from django.core.mail import send_mail

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    # --- Валидация ---
    buyer_name = data.get("buyer_name", "").strip()
    buyer_phone = data.get("buyer_phone", "").strip()
    if not buyer_name or not buyer_phone:
        return JsonResponse(
            {"success": False, "error": "Имя и телефон покупателя обязательны"},
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
    recipient_phone = data.get("recipient_phone", "").strip()
    message = data.get("message", "").strip()

    # --- Создание Order ---
    order = Order.objects.create(
        order_type="certificate",
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

    # --- Telegram ---
    tg_token = getattr(django_settings, "TELEGRAM_BOT_TOKEN", "")
    tg_chat = getattr(django_settings, "TELEGRAM_CHAT_ID", "")
    if tg_token and tg_chat:
        try:
            value_str = (
                f"{nominal:,.0f} \u20bd"
                if cert_type == "nominal"
                else str(service)
            )
            text = (
                f"\U0001f381 \u041d\u043e\u0432\u0430\u044f \u0437\u0430\u044f\u0432\u043a\u0430 \u043d\u0430 \u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442!\n\n"
                f"\U0001f4b0 {value_str}\n"
                f"\U0001f464 {buyer_name}, {buyer_phone}\n"
            )
            if recipient_name:
                text += f"\U0001f380 \u041f\u043e\u043b\u0443\u0447\u0430\u0442\u0435\u043b\u044c: {recipient_name}\n"
            if recipient_phone:
                text += f"\U0001f4f1 {recipient_phone}\n"
            if message:
                text += f"\U0001f4ac {message}\n"
            text += f"\n\u2116 \u0437\u0430\u043a\u0430\u0437\u0430: {order.number}"

            http_requests.post(
                f"https://api.telegram.org/bot{tg_token}/sendMessage",
                json={"chat_id": tg_chat, "text": text, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception as e:
            logger.warning(f"Telegram notification failed: {e}")

    # --- Email ---
    admin_email = getattr(django_settings, "ADMIN_NOTIFICATION_EMAIL", "")
    if admin_email:
        try:
            send_mail(
                subject=f"\u0417\u0430\u044f\u0432\u043a\u0430 \u043d\u0430 \u0441\u0435\u0440\u0442\u0438\u0444\u0438\u043a\u0430\u0442: {order.number}",
                message=(
                    f"\u041f\u043e\u043a\u0443\u043f\u0430\u0442\u0435\u043b\u044c: {buyer_name}, {buyer_phone}\n"
                    f"\u041f\u043e\u043b\u0443\u0447\u0430\u0442\u0435\u043b\u044c: {recipient_name or chr(8212)}\n"
                    f"\u0422\u0438\u043f: {cert.get_certificate_type_display()}\n"
                    f"\u041d\u043e\u043c\u0438\u043d\u0430\u043b: {nominal}"
                ),
                from_email=None,
                recipient_list=[admin_email],
                fail_silently=True,
            )
        except Exception:
            pass

    return JsonResponse({
        "success": True,
        "message": "\u0417\u0430\u044f\u0432\u043a\u0430 \u043f\u0440\u0438\u043d\u044f\u0442\u0430! \u041c\u0435\u043d\u0435\u0434\u0436\u0435\u0440 \u0441\u0432\u044f\u0436\u0435\u0442\u0441\u044f \u0441 \u0432\u0430\u043c\u0438 \u0434\u043b\u044f \u043e\u043f\u043b\u0430\u0442\u044b.",
        "order_number": order.number,
    })


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
