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

logger = logging.getLogger(__name__)

@require_GET
def api_get_staff(request):
    """
    API endpoint: получить список мастеров из YClients
    
    Query параметры:
    - show_all=1  показать всех (включая уволенных/скрытых)
    - show_all=0  только активные (по умолчанию)
    """
    try:
        from services_app.yclients_api import get_yclients_api, YClientsAPIError
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Получаем параметр фильтрации
        show_all = request.GET.get('show_all', '0') == '1'
        
        # Получаем API клиент
        api = get_yclients_api()
        
        # Получаем список мастеров
        all_staff = api.get_staff()
        
        logger.info(f"📥 Получено мастеров из YClients: {len(all_staff)}")
        
        # Статистика (считаем ДО фильтрации!)
        stats = {
            'total': len(all_staff),
            'active': 0,
            'bookable': 0,
            'hidden': 0,
            'fired': 0,
            'deleted': 0,
        }
        
        # Форматируем мастеров
        formatted_staff = []
        
        for s in all_staff:
            is_hidden = s.get('hidden', 0) == 1
            is_fired = s.get('fired', 0) == 1
            is_deleted = s.get('status', 0) == 1
            is_bookable = s.get('bookable', False)
            
            # Обновляем статистику (для ВСЕХ мастеров)
            if is_hidden:
                stats['hidden'] += 1
            if is_fired:
                stats['fired'] += 1
            if is_deleted:
                stats['deleted'] += 1
            if is_bookable:
                stats['bookable'] += 1
            
            # Определяем доступность
            is_available = not is_hidden and not is_fired and not is_deleted
            
            if is_available:
                stats['active'] += 1
            
            # Определяем статус
            if is_deleted:
                availability_status = 'deleted'
                availability_info = 'Удалён из системы'
            elif is_fired:
                availability_status = 'fired'
                availability_info = 'Уволен'
            elif is_hidden:
                availability_status = 'hidden'
                availability_info = 'Скрыт от онлайн-записи'
            elif not is_bookable:
                availability_status = 'not_configured'
                availability_info = 'Онлайн-запись не настроена'
            else:
                availability_status = 'available'
                availability_info = 'Доступен для записи'
            
            # ФИЛЬТР: Пропускаем неактивных (если show_all=0)
            if not show_all and not is_available:
                logger.debug(f"⏭️ Пропущен мастер {s.get('name')}: hidden={is_hidden}, fired={is_fired}, deleted={is_deleted}")
                continue
            
            formatted_staff.append({
                'id': s['id'],
                'name': s.get('name', ''),
                'specialization': s.get('specialization', ''),
                'avatar': s.get('avatar', ''),
                'avatar_big': s.get('avatar_big', ''),
                'rating': s.get('rating', 0),
                'votes_count': s.get('votes_count', 0),
                'comments_count': s.get('comments_count', 0),
                'information': s.get('information', ''),
                # Флаги
                'is_available': is_available,
                'bookable': is_bookable,
                'hidden': is_hidden,
                'fired': is_fired,
                'deleted': is_deleted,
                # Статус для UI
                'availability_status': availability_status,
                'availability_info': availability_info,
            })
        
        logger.info(f"✅ Отфильтровано мастеров: {len(formatted_staff)} из {stats['total']}")
        logger.info(f"📊 Активных: {stats['active']}, Доступных для записи: {stats['bookable']}")
        
        return JsonResponse({
            'success': True,
            'data': formatted_staff,
            'count': len(formatted_staff),
            'meta': stats
        })
        
    except Exception as e:
        logger.exception(f"❌ Error in api_get_staff: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'meta': {'total': 0, 'active': 0, 'bookable': 0}
        }, status=500)

@require_GET
def api_available_times(request):
    """
    API endpoint: получить свободные временные слоты
    
    Query параметры:
    - staff_id (обязательно): ID мастера
    - date (обязательно): дата в формате YYYY-MM-DD
    - service_id (опционально): ID услуги
    """
    try:
        from services_app.yclients_api import get_yclients_api, YClientsAPIError
        from datetime import datetime
        import logging
        
        logger = logging.getLogger(__name__)
        logger.info(f"Start api_available_times")
        logger.info(f"Request: {request.GET}")
        
        # Валидация параметров
        staff_id = request.GET.get('staff_id')
        date = request.GET.get('date')
        service_id = request.GET.get('service_id')
        
        if not staff_id:
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameter: staff_id'
            }, status=400)
        
        if not date:
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameter: date'
            }, status=400)
        
        # Валидация формата даты
        try:
            datetime.strptime(date, '%Y-%m-%d')
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid date format. Use YYYY-MM-DD'
            }, status=400)
        
        # Получаем API клиент
        api = get_yclients_api()
        
        # Получаем информацию о мастере
        # ИСПРАВЛЕНИЕ: get_staff() возвращает СПИСОК, не словарь!
        staff_list = api.get_staff()
        
        # Проверяем, что получили список
        if not isinstance(staff_list, list):
            logger.error(f"Unexpected get_staff() response: {type(staff_list)}")
            return JsonResponse({
                'success': False,
                'error': 'Invalid staff data format'
            }, status=500)
        
        # Ищем мастера по ID
        master = None
        for s in staff_list:
            if str(s.get('id')) == str(staff_id):
                master = s
                break
        
        if not master:
            return JsonResponse({
                'success': False,
                'error': f'Staff member {staff_id} not found'
            }, status=404)
        
        logger.info(f"🔍 Получение времени для мастера: {master.get('name')}")
        
        # Получаем свободные слоты
        times = api.get_available_times(
            staff_id=int(staff_id),
            date=date,
            service_id=int(service_id) if service_id else None
        )
        
        logger.info(f"✅ Найдено слотов: {len(times)}")
        
        return JsonResponse({
            'success': True,
            'data': {
                'staff_id': int(staff_id),
                'staff_name': master.get('name', ''),
                'staff_specialization': master.get('specialization', ''),
                'date': date,
                'service_id': int(service_id) if service_id else None,
                'times': times,
                'count': len(times)
            }
        })
        
    except YClientsAPIError as e:
        logger.exception(f"❌ YClients API Error: {e}")
        return JsonResponse({
            'success': False,
            'error': f'YClients API error: {str(e)}'
        }, status=500)
    except Exception as e:
        logger.exception(f"❌ Unexpected error in api_available_times: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@csrf_exempt
@require_POST
def api_create_booking(request):
    """API: создать запись"""
    try:
        from services_app.yclients_api import get_yclients_api, YClientsAPIError
        from datetime import datetime
        import logging
        
        logger = logging.getLogger(__name__)
        
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
        
        # Валидация
        required = ['staff_id', 'service_ids', 'date', 'time', 'client']
        missing = [f for f in required if f not in body]
        if missing:
            return JsonResponse({
                'success': False,
                'error': f'Missing: {", ".join(missing)}'
            }, status=400)
        
        staff_id = body['staff_id']
        service_ids = body['service_ids']
        date = body['date']
        time = body['time']
        client = body['client']
        comment = body.get('comment', '')
        
        # Валидация client
        if not isinstance(client, dict):
            return JsonResponse({'success': False, 'error': 'client must be object'}, status=400)
        
        if 'name' not in client or 'phone' not in client:
            return JsonResponse({'success': False, 'error': 'client needs name and phone'}, status=400)
        
        # Валидация service_ids
        if not isinstance(service_ids, list) or not service_ids:
            return JsonResponse({'success': False, 'error': 'service_ids must be array'}, status=400)
        
        # Формируем datetime
        booking_datetime = f"{date}T{time}:00"
        
        # API клиент
        api = get_yclients_api()
        
        # Информация о мастере
        staff_list = api.get_staff()
        master = next((s for s in staff_list if s['id'] == staff_id), None)
        
        if not master:
            return JsonResponse({'success': False, 'error': f'Staff {staff_id} not found'}, status=404)
        
        logger.info(f"📝 Создание записи: staff={master['name']}, datetime={booking_datetime}")
        
        # Создаём запись
        booking = api.create_booking(
            staff_id=staff_id,
            services=service_ids,
            datetime=booking_datetime,
            client=client,
            comment=comment
        )
        
        logger.info(f"✅ Запись создана! Record ID: {booking.get('record_id')}")
        
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
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    except Exception as e:
        logger.exception(f"❌ Error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)