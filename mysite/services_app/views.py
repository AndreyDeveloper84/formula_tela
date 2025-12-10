""" from django.shortcuts import render

from django.db.models import Prefetch
from .models import Service, ServiceOption, ServiceCategory

def services(request):
    options_qs = ServiceOption.objects.filter(is_active=True).order_by(
        "order", "duration_min", "unit_type", "units"
        )
    services_qs = Service.objects.filter(is_active=True).prefetch_related(
        Prefetch("options", queryset=options_qs)
    ).select_related("category").order_by("category__order", "name")

    categories = ServiceCategory.objects.prefetch_related(
        Prefetch("services", queryset=services_qs)
    ).order_by("order", "name")

    return render(request, "website/services.html", {"categories": categories})
 """

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from datetime import datetime

from services_app.models import ServiceOption
from services_app.yclients_api import get_yclients_api, YClientsAPIError
from services_app.forms import (
    BookingStep1Form,
    BookingStep2Form,
    BookingStep3Form,
    BookingStep4Form,
)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def get_booking_session(request):
    """Получить данные записи из сессии"""
    return request.session.get('booking_data', {})


def set_booking_session(request, data):
    """Сохранить данные записи в сессию"""
    request.session['booking_data'] = data
    request.session.modified = True


def clear_booking_session(request):
    """Очистить данные записи из сессии"""
    if 'booking_data' in request.session:
        del request.session['booking_data']


# ============================================================
# ПОШАГОВАЯ ЗАПИСЬ (4 шага)
# ============================================================

def booking_step1(request):
    """
    Шаг 1: Выбор услуги
    """
    if request.method == 'POST':
        form = BookingStep1Form(request.POST)
        if form.is_valid():
            # Сохраняем выбранную услугу в сессию
            option = form.cleaned_data['service_option']
            booking_data = {
                'service_option_id': option.id,
                'service_name': str(option.service.name),
                'option_details': str(option),
                'price': float(option.price),
            }
            set_booking_session(request, booking_data)
            return redirect('website:booking_step2')
    else:
        form = BookingStep1Form()
    
    context = {
        'form': form,
        'step': 1,
        'total_steps': 4,
    }
    return render(request, 'website/booking_step1.html', context)


def booking_step2(request):
    """
    Шаг 2: Выбор мастера
    """
    booking_data = get_booking_session(request)
    
    # Проверяем что услуга выбрана
    if not booking_data.get('service_option_id'):
        messages.warning(request, 'Сначала выберите услугу')
        return redirect('website:booking_step1')
    
    service_option_id = booking_data['service_option_id']
    
    if request.method == 'POST':
        form = BookingStep2Form(service_option_id, request.POST)
        if form.is_valid():
            # Сохраняем выбранного мастера
            staff_id = form.cleaned_data['staff_id']
            booking_data['staff_id'] = staff_id
            
            # Получаем имя мастера
            if staff_id == '0':
                booking_data['staff_name'] = 'Любой мастер'
            else:
                # Получаем из YClients
                try:
                    api = get_yclients_api()
                    staff_list = api.get_staff()
                    staff = next((s for s in staff_list if str(s['id']) == staff_id), None)
                    booking_data['staff_name'] = staff['name'] if staff else 'Мастер не найден'
                except YClientsAPIError:
                    booking_data['staff_name'] = f'Мастер #{staff_id}'
            
            set_booking_session(request, booking_data)
            return redirect('website:booking_step3')
    else:
        form = BookingStep2Form(service_option_id)
    
    context = {
        'form': form,
        'step': 2,
        'total_steps': 4,
        'booking_data': booking_data,
    }
    return render(request, 'website/booking_step2.html', context)


def booking_step3(request):
    """
    Шаг 3: Выбор даты и времени
    """
    booking_data = get_booking_session(request)
    
    # Проверяем что предыдущие шаги пройдены
    if not booking_data.get('service_option_id') or not booking_data.get('staff_id'):
        messages.warning(request, 'Сначала выберите услугу и мастера')
        return redirect('website:booking_step1')
    
    service_option_id = booking_data['service_option_id']
    staff_id = booking_data['staff_id']
    
    if request.method == 'POST':
        form = BookingStep3Form(service_option_id, staff_id, request.POST)
        if form.is_valid():
            # Сохраняем дату и время
            date = form.cleaned_data['date']
            time = form.cleaned_data['time']
            
            booking_data['date'] = date.isoformat()
            booking_data['time'] = time
            booking_data['datetime_display'] = f"{date.strftime('%d.%m.%Y')} в {time}"
            
            set_booking_session(request, booking_data)
            return redirect('website:booking_step4')
    else:
        form = BookingStep3Form(service_option_id, staff_id)
    
    context = {
        'form': form,
        'step': 3,
        'total_steps': 4,
        'booking_data': booking_data,
    }
    return render(request, 'website/booking_step3.html', context)


def booking_step4(request):
    """
    Шаг 4: Ввод данных клиента и подтверждение
    """
    booking_data = get_booking_session(request)
    
    # Проверяем что все предыдущие шаги пройдены
    required_fields = ['service_option_id', 'staff_id', 'date', 'time']
    if not all(booking_data.get(field) for field in required_fields):
        messages.warning(request, 'Пожалуйста, пройдите все шаги записи')
        return redirect('website:booking_step1')
    
    if request.method == 'POST':
        form = BookingStep4Form(request.POST)
        if form.is_valid():
            try:
                # Получаем данные клиента
                client_name = form.cleaned_data['name']
                client_phone = form.cleaned_data['phone']
                client_email = form.cleaned_data.get('email', '')
                comment = form.cleaned_data.get('comment', '')
                
                # Получаем вариант услуги
                option = ServiceOption.objects.get(pk=booking_data['service_option_id'])
                
                # Формируем datetime для YClients
                date_obj = datetime.fromisoformat(booking_data['date'])
                time_str = booking_data['time']
                datetime_str = f"{date_obj.strftime('%Y-%m-%d')} {time_str}:00"
                
                # Создаём запись через YClients API
                api = get_yclients_api()
                
                booking_result = api.create_booking(
                    service_id=int(option.yclients_service_id),
                    staff_id=int(booking_data['staff_id']),
                    datetime_str=datetime_str,
                    client_name=client_name,
                    client_phone=client_phone,
                    client_email=client_email,
                    comment=comment,
                    send_sms=True,
                    notify_by_sms=24,  # SMS за 24 часа до записи
                )
                
                # Сохраняем результат в сессию для страницы успеха
                booking_data['client_name'] = client_name
                booking_data['client_phone'] = client_phone
                booking_data['client_email'] = client_email
                booking_data['comment'] = comment
                booking_data['booking_id'] = booking_result.get('id')
                booking_data['success'] = True
                
                set_booking_session(request, booking_data)
                
                messages.success(request, '✅ Запись успешно создана!')
                return redirect('website:booking_success')
                
            except ServiceOption.DoesNotExist:
                messages.error(request, '❌ Выбранная услуга не найдена')
                return redirect('website:booking_step1')
                
            except YClientsAPIError as e:
                messages.error(request, f'❌ Ошибка при создании записи: {str(e)}')
                # Остаёмся на той же странице, чтобы клиент мог повторить
                
            except Exception as e:
                messages.error(request, f'❌ Неожиданная ошибка: {str(e)}')
    else:
        form = BookingStep4Form()
    
    context = {
        'form': form,
        'step': 4,
        'total_steps': 4,
        'booking_data': booking_data,
    }
    return render(request, 'website/booking_step4.html', context)


def booking_success(request):
    """
    Страница успешной записи
    """
    booking_data = get_booking_session(request)
    
    if not booking_data.get('success'):
        messages.warning(request, 'Запись не найдена')
        return redirect('website:home')
    
    context = {
        'booking_data': booking_data,
    }
    
    # Очищаем сессию после показа
    # (можно закомментировать, если нужно сохранить для повторного просмотра)
    # clear_booking_session(request)
    
    return render(request, 'website/booking_success.html', context)


# ============================================================
# AJAX API ДЛЯ ДИНАМИЧЕСКОЙ ЗАГРУЗКИ
# ============================================================

@require_http_methods(["GET"])
def api_get_staff(request):
    """
    AJAX API: Получить список мастеров для услуги
    
    GET /api/booking/staff/?service_option_id=123
    
    Returns:
        JSON: [{"id": 1, "name": "Мария"}, ...]
    """
    service_option_id = request.GET.get('service_option_id')
    
    if not service_option_id:
        return JsonResponse({'error': 'service_option_id is required'}, status=400)
    
    try:
        option = ServiceOption.objects.get(pk=service_option_id)
        
        if not option.yclients_service_id:
            return JsonResponse({'error': 'Service not linked to YClients'}, status=400)
        
        api = get_yclients_api()
        staff_list = api.get_staff(service_id=int(option.yclients_service_id))
        
        # Фильтруем только bookable мастеров
        result = [
            {'id': s['id'], 'name': s['name']}
            for s in staff_list
            if s.get('bookable', True)
        ]
        
        return JsonResponse({'staff': result})
        
    except ServiceOption.DoesNotExist:
        return JsonResponse({'error': 'Service option not found'}, status=404)
    except YClientsAPIError as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def api_get_available_times(request):
    """
    AJAX API: Получить свободное время
    
    GET /api/booking/times/?service_option_id=123&staff_id=456&date=2025-01-15
    
    Returns:
        JSON: {"times": ["09:00", "10:00", ...]}
    """
    service_option_id = request.GET.get('service_option_id')
    staff_id = request.GET.get('staff_id')
    date = request.GET.get('date')
    
    if not all([service_option_id, staff_id, date]):
        return JsonResponse({'error': 'Missing required parameters'}, status=400)
    
    try:
        option = ServiceOption.objects.get(pk=service_option_id)
        
        if not option.yclients_service_id:
            return JsonResponse({'error': 'Service not linked to YClients'}, status=400)
        
        api = get_yclients_api()
        times = api.get_available_times(
            service_id=int(option.yclients_service_id),
            staff_id=int(staff_id),
            date=date
        )
        
        return JsonResponse({'times': times})
        
    except ServiceOption.DoesNotExist:
        return JsonResponse({'error': 'Service option not found'}, status=404)
    except YClientsAPIError as e:
        return JsonResponse({'error': str(e)}, status=500)


# ============================================================
# БЫСТРАЯ ЗАПИСЬ (одна страница, как на скриншоте)
# ============================================================

def booking_quick(request):
    """
    Быстрая запись на одной странице (как на скриншоте)
    
    Работает через AJAX для динамической подгрузки мастеров/времени
    """
    # Получаем service_option_id из GET параметра (если есть)
    service_option_id = request.GET.get('service_option_id')
    
    # Если услуга передана, получаем её данные
    selected_option = None
    if service_option_id:
        try:
            selected_option = ServiceOption.objects.select_related('service').get(
                pk=service_option_id,
                is_active=True
            )
        except ServiceOption.DoesNotExist:
            messages.warning(request, 'Выбранная услуга не найдена')
    
    # Получаем все активные услуги для выбора
    options = (
        ServiceOption.objects
        .filter(is_active=True, service__is_active=True)
        .select_related('service', 'service__category')
        .order_by('service__category__order', 'service__name', 'order')
    )
    
    context = {
        'options': options,
        'selected_option': selected_option,
    }
    return render(request, 'website/booking_quick.html', context)


@require_http_methods(["POST"])
def booking_quick_submit(request):
    """
    Обработка быстрой записи (AJAX)
    
    POST /api/booking/quick-submit/
    {
        "service_option_id": 123,
        "staff_id": 456,
        "date": "2025-01-15",
        "time": "14:00",
        "name": "Иван",
        "phone": "79991234567",
        "email": "ivan@example.com",
        "comment": "..."
    }
    """
    import json
    
    try:
        data = json.loads(request.body)
        
        # Валидация
        required = ['service_option_id', 'staff_id', 'date', 'time', 'name', 'phone']
        if not all(data.get(field) for field in required):
            return JsonResponse({'error': 'Missing required fields'}, status=400)
        
        # Получаем услугу
        option = ServiceOption.objects.get(pk=data['service_option_id'])
        
        if not option.yclients_service_id:
            return JsonResponse({'error': 'Service not linked to YClients'}, status=400)
        
        # Формируем datetime
        datetime_str = f"{data['date']} {data['time']}:00"
        
        # Создаём запись
        api = get_yclients_api()
        booking_result = api.create_booking(
            service_id=int(option.yclients_service_id),
            staff_id=int(data['staff_id']),
            datetime_str=datetime_str,
            client_name=data['name'],
            client_phone=data['phone'],
            client_email=data.get('email', ''),
            comment=data.get('comment', ''),
            send_sms=True,
        )
        
        return JsonResponse({
            'success': True,
            'booking_id': booking_result.get('id'),
            'message': '✅ Запись успешно создана! Мы отправили SMS на ваш номер.',
        })
        
    except ServiceOption.DoesNotExist:
        return JsonResponse({'error': 'Service not found'}, status=404)
    except YClientsAPIError as e:
        return JsonResponse({'error': str(e)}, status=500)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Unexpected error: {str(e)}'}, status=500)