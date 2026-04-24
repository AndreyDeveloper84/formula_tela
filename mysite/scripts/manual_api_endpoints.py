#!/usr/bin/env python
"""
Быстрый тест YClients API с разными endpoints

Проверяет какие endpoints работают быстро
"""

import os
import sys
import django
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mysite'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings.dev')
django.setup()

from services_app.yclients_api import get_yclients_api, YClientsAPIError


def test_endpoint(name: str, func, *args, **kwargs):
    """Тестирует endpoint и измеряет время"""
    print(f"\n{'='*60}")
    print(f"🧪 Тестирование: {name}")
    print(f"{'='*60}")
    
    start = time.time()
    try:
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        
        if isinstance(result, list):
            print(f"✅ Успешно! Время: {elapsed:.2f}с")
            print(f"   Получено записей: {len(result)}")
            if result:
                print(f"   Первая запись: {result[0].get('name') or result[0].get('title')}")
        else:
            print(f"✅ Успешно! Время: {elapsed:.2f}с")
            print(f"   Тип результата: {type(result)}")
        
        return True
        
    except YClientsAPIError as e:
        elapsed = time.time() - start
        print(f"❌ Ошибка! Время: {elapsed:.2f}с")
        print(f"   {e}")
        return False
    except Exception as e:
        elapsed = time.time() - start
        print(f"❌ Неожиданная ошибка! Время: {elapsed:.2f}с")
        print(f"   {e}")
        return False


def main():
    print("\n🔬 ТЕСТИРОВАНИЕ YCLIENTS API ENDPOINTS\n")
    
    api = get_yclients_api()
    
    # Тест 1: Получение всех мастеров (обычно быстро)
    test_endpoint(
        "get_staff() - все мастера",
        api.get_staff
    )
    
    # Тест 2: Получение всех услуг компании (может быть долго)
    test_endpoint(
        "get_services() - все услуги компании",
        api.get_services
    )
    
    # Получаем первого мастера для дальнейших тестов
    try:
        staff_list = api.get_staff()
        if staff_list:
            first_staff = staff_list[0]
            staff_id = first_staff['id']
            staff_name = first_staff['name']
            
            print(f"\n📌 Используем мастера: {staff_name} (ID: {staff_id})")
            
            # Тест 3: Услуги конкретного мастера (ПРОБЛЕМНЫЙ)
            test_endpoint(
                f"get_staff_services({staff_id}) - услуги мастера",
                api.get_staff_services,
                staff_id
            )
            
            # Тест 4: Мастера для конкретной услуги
            services = api.get_services()
            if services:
                first_service_id = services[0]['id']
                test_endpoint(
                    f"get_staff(service_id={first_service_id}) - мастера для услуги",
                    api.get_staff,
                    service_id=first_service_id
                )
        
    except Exception as e:
        print(f"\n❌ Не удалось получить мастеров: {e}")
    
    print(f"\n{'='*60}")
    print("✅ Тестирование завершено")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()