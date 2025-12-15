from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from collections import defaultdict
from django.db.models import Prefetch
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_exempt
from services_app.yclients_api import get_yclients_api, YClientsAPIError
import logging
import json

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

    ctx = {
        "settings": _settings(),
        "top_items": top_items,
        "categories": categories,
        "masters": masters,
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

logger = logging.getLogger(__name__)


@require_GET
@csrf_exempt
def api_available_times(request):
    """
    API: получить список доступных времён для записи.
    """
    try:
        from services_app.yclients_api import get_yclients_api, YClientsAPIError
        import logging
        
        logger = logging.getLogger(__name__)
        
        staff_id = request.GET.get('staff_id')
        date = request.GET.get('date')
        
        if not staff_id or not date:
            return JsonResponse({
                'success': False,
                'error': 'staff_id and date are required'
            }, status=400)
        
        logger.info(f"⏰ Запрос доступных времён: мастер={staff_id}, дата={date}")
        
        api = get_yclients_api()
        
        try:
            times = api.get_available_times(
                staff_id=int(staff_id),
                date=date
            )
            
            logger.info(f"✅ Найдено свободных слотов: {len(times)}")
            
            # ВСЕГДА возвращаем success=true, даже если слотов 0
            return JsonResponse({
                'success': True,
                'data': {
                    'times': times,
                    'count': len(times),
                    'date': date,
                    'staff_id': staff_id
                }
            })
            
        except YClientsAPIError as e:
            logger.error(f"❌ YClients API error: {e}")
            # Возвращаем пустой массив вместо ошибки
            return JsonResponse({
                'success': True,
                'data': {
                    'times': [],
                    'count': 0,
                    'date': date,
                    'staff_id': staff_id,
                    'warning': 'Нет доступных слотов на эту дату'
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

def service_detail(request, service_id):
    """Страница конкретной услуги с формой бронирования"""
    from services_app.models import Service
    import logging
    
    logger = logging.getLogger(__name__)
    
    try:
        # Сначала пытаемся найти активную услугу
        service = Service.objects.filter(pk=service_id, is_active=True).first()
        
        if not service:
            # Проверяем, существует ли услуга вообще (для отладки)
            service_exists = Service.objects.filter(pk=service_id).exists()
            if service_exists:
                logger.warning(f"⚠️ Услуга {service_id} существует, но неактивна (is_active=False)")
                # Можно показать услугу даже если она неактивна (для отладки на staging)
                # Или вернуть 404 с более информативным сообщением
                service = Service.objects.get(pk=service_id)
            else:
                logger.error(f"❌ Услуга {service_id} не найдена в базе данных")
                from django.http import Http404
                raise Http404(f"Услуга с ID {service_id} не найдена")
        
        logger.info(f"✅ Загружена услуга: {service.name} (ID: {service_id}, active: {service.is_active})")
        
        # Получаем только активные опции с YClients ID
        service.options_filtered = service.options.filter(
            is_active=True,
            yclients_service_id__isnull=False
        ).exclude(yclients_service_id='').order_by('order', 'duration_min')
        
        logger.info(f"📋 Найдено активных вариантов с YClients ID: {service.options_filtered.count()}")
        
        return render(request, 'website/service_detail.html', {
            'settings': _settings(),
            'service': service,
        })
        
    except Service.DoesNotExist:
        logger.error(f"❌ Услуга {service_id} не найдена (DoesNotExist)")
        from django.http import Http404
        raise Http404(f"Услуга с ID {service_id} не найдена")
    except Exception as e:
        logger.exception(f"❌ Ошибка при загрузке услуги {service_id}: {e}")
        from django.http import Http404
        raise Http404(f"Ошибка при загрузке услуги: {str(e)}")

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
        api = get_yclients_api()
        
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