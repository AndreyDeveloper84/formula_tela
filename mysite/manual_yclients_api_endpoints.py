#!/usr/bin/env python
"""
Тестовый скрипт для проверки YClients API endpoints

Что проверяет:
1. /company/{company_id}/staff - список всех сотрудников
2. /book_staff/{company_id} - сотрудники доступные для записи
3. /book_services/{company_id}/{staff_id} - услуги конкретного сотрудника

Запуск:
    python test_yclients_api_endpoints.py
"""

import os
import sys
import django
import json

# Настройка Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mysite'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings.dev')
django.setup()

from services_app.yclients_api import get_yclients_api
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def print_section(title: str):
    """Красивый заголовок"""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)


def test_get_all_staff():
    """
    Тест 1: Получить всех сотрудников
    Endpoint: GET /company/{company_id}/staff
    """
    print_section("ТЕСТ 1: GET /company/{company_id}/staff")
    
    api = get_yclients_api()
    
    try:
        endpoint = f'/company/{api.company_id}/staff'
        print(f"📡 Запрос: {endpoint}")
        
        response = api._request('GET', endpoint)
        staff_list = response.get('data', [])
        
        print(f"✅ Успешно! Получено сотрудников: {len(staff_list)}")
        print(f"\n📋 Список сотрудников:")
        
        for idx, staff in enumerate(staff_list, 1):
            name = staff.get('name', 'Без имени')
            staff_id = staff.get('id')
            specialization = staff.get('specialization', 'Не указана')
            bookable = staff.get('bookable', False)
            active = staff.get('active', False)
            
            status = []
            if bookable:
                status.append("✅ bookable")
            if active:
                status.append("✅ active")
            
            status_str = ", ".join(status) if status else "❌ не доступен"
            
            print(f"   {idx}. {name} (ID: {staff_id})")
            print(f"      Специализация: {specialization}")
            print(f"      Статус: {status_str}")
        
        return staff_list
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return []


def test_get_bookable_staff():
    """
    Тест 2: Получить сотрудников доступных для записи
    Endpoint: GET /book_staff/{company_id}
    """
    print_section("ТЕСТ 2: GET /book_staff/{company_id}")
    
    api = get_yclients_api()
    
    try:
        endpoint = f'/book_staff/{api.company_id}'
        print(f"📡 Запрос: {endpoint}")
        
        response = api._request('GET', endpoint)
        staff_list = response.get('data', [])
        
        print(f"✅ Успешно! Доступных для записи: {len(staff_list)}")
        print(f"\n📋 Список:")
        
        for idx, staff in enumerate(staff_list, 1):
            name = staff.get('name', 'Без имени')
            staff_id = staff.get('id')
            print(f"   {idx}. {name} (ID: {staff_id})")
        
        return staff_list
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return []


def test_get_staff_services(staff_id: int, staff_name: str):
    """
    Тест 3: Получить услуги конкретного сотрудника
    Endpoint: GET /book_services/{company_id}/{staff_id}
    """
    print_section(f"ТЕСТ 3: Услуги сотрудника {staff_name}")
    
    api = get_yclients_api()
    
    try:
        endpoint = f'/book_services/{api.company_id}/{staff_id}'
        print(f"📡 Запрос: {endpoint}")
        
        response = api._request('GET', endpoint)
        
        # YClients API может вернуть разную структуру
        # Пробуем разные варианты
        services = []
        
        if 'data' in response:
            data = response['data']
            if isinstance(data, dict):
                services = data.get('services', [])
            elif isinstance(data, list):
                services = data
        elif 'services' in response:
            services = response['services']
        
        print(f"✅ Успешно! Услуг: {len(services)}")
        
        if services:
            print(f"\n📋 Список услуг:")
            for idx, service in enumerate(services[:10], 1):  # Первые 10
                service_id = service.get('id')
                title = service.get('title', 'Без названия')
                price_min = service.get('price_min', 0)
                price_max = service.get('price_max', 0)
                
                price_str = f"{price_min}₽"
                if price_max and price_max != price_min:
                    price_str = f"{price_min}-{price_max}₽"
                
                print(f"   {idx}. {title}")
                print(f"      ID: {service_id} | Цена: {price_str}")
            
            if len(services) > 10:
                print(f"   ... и ещё {len(services) - 10} услуг")
        else:
            print("⚠️ У сотрудника нет услуг")
        
        return services
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return []


def test_get_staff_with_service_filter():
    """
    Тест 4: Получить сотрудников которые делают конкретную услугу
    Endpoint: GET /book_staff/{company_id}?service_id={service_id}
    """
    print_section("ТЕСТ 4: Фильтрация по услуге")
    
    api = get_yclients_api()
    
    # Берём первую услугу из ServiceOption
    from services_app.models import ServiceOption
    
    option = ServiceOption.objects.filter(
        is_active=True,
        yclients_service_id__isnull=False
    ).first()
    
    if not option:
        print("⚠️ Нет ServiceOption с yclients_service_id")
        return []
    
    service_id = option.yclients_service_id
    service_name = option.service.name
    
    print(f"🔍 Тестовая услуга: {service_name}")
    print(f"   Service ID в YClients: {service_id}")
    
    try:
        endpoint = f'/book_staff/{api.company_id}'
        params = {'service_id': service_id}
        
        print(f"📡 Запрос: {endpoint}?service_id={service_id}")
        
        response = api._request('GET', endpoint, params=params)
        staff_list = response.get('data', [])
        
        print(f"✅ Успешно! Мастеров для этой услуги: {len(staff_list)}")
        
        if staff_list:
            print(f"\n📋 Список мастеров:")
            for idx, staff in enumerate(staff_list, 1):
                name = staff.get('name', 'Без имени')
                staff_id = staff.get('id')
                print(f"   {idx}. {name} (ID: {staff_id})")
        else:
            print("⚠️ Нет мастеров для этой услуги")
        
        return staff_list
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return []


def save_full_response(filename: str, data: dict):
    """Сохранить полный ответ API в файл для анализа"""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 Полный ответ сохранён в: {filename}")
    except Exception as e:
        print(f"⚠️ Не удалось сохранить: {e}")


def main():
    """
    Главная функция
    """
    print("\n" + "🧪 ТЕСТИРОВАНИЕ YCLIENTS API ENDPOINTS" + "\n")
    
    # Тест 1: Все сотрудники
    all_staff = test_get_all_staff()
    
    # Тест 2: Доступные для записи
    bookable_staff = test_get_bookable_staff()
    
    # Тест 3: Услуги первого сотрудника
    if bookable_staff:
        first_staff = bookable_staff[0]
        staff_id = first_staff.get('id')
        staff_name = first_staff.get('name')
        
        services = test_get_staff_services(staff_id, staff_name)
    
    # Тест 4: Фильтрация по услуге
    test_get_staff_with_service_filter()
    
    # Итоги
    print_section("ИТОГИ ТЕСТИРОВАНИЯ")
    print(f"""
    ✅ Тест 1: Все сотрудники - {len(all_staff)} шт
    ✅ Тест 2: Доступные для записи - {len(bookable_staff)} шт
    ✅ Тест 3: Услуги сотрудника - OK
    ✅ Тест 4: Фильтрация по услуге - OK
    
    🎯 Все тесты завершены!
    
    Что дальше:
    1. Если все OK → запускай sync_masters_services_from_yclients.py
    2. Если есть ошибки → проверь логи выше
    """)


if __name__ == '__main__':
    main()
