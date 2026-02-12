#!/usr/bin/env python
"""
Диагностика и синхронизация YClients → Django

Что делает:
1. Проверяет настройки .env
2. Тестирует подключение к YClients API
3. Запускает синхронизацию мастеров
4. Показывает результаты

Запуск:
    python diagnose_and_sync.py
"""

import os
import sys
import django

# Настройка Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mysite'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings.dev')
django.setup()

from services_app.yclients_api import get_yclients_api, YClientsAPIError
from services_app.models import Master, Service, ServiceOption
from django.conf import settings


def print_section(title: str, emoji: str = "📋"):
    """Красивый заголовок"""
    print("\n" + "="*70)
    print(f"{emoji} {title}")
    print("="*70)


def step1_check_settings():
    """Шаг 1: Проверка настроек"""
    print_section("ШАГ 1: Проверка настроек .env", "🔍")
    
    required = {
        'YCLIENTS_PARTNER_TOKEN': settings.YCLIENTS_PARTNER_TOKEN,
        'YCLIENTS_USER_TOKEN': settings.YCLIENTS_USER_TOKEN,
        'YCLIENTS_COMPANY_ID': settings.YCLIENTS_COMPANY_ID,
    }
    
    all_ok = True
    
    for name, value in required.items():
        if value:
            # Показываем только первые/последние символы токена
            if 'TOKEN' in name:
                masked = f"{value[:8]}...{value[-4:]}" if len(value) > 12 else "***"
                print(f"✅ {name}: {masked}")
            else:
                print(f"✅ {name}: {value}")
        else:
            print(f"❌ {name}: НЕ ЗАДАН!")
            all_ok = False
    
    if not all_ok:
        print("\n❌ ОШИБКА: Не все настройки заданы!")
        print("Проверь файл .env")
        return False
    
    print("\n✅ Все настройки заданы")
    return True


def step2_test_api_connection():
    """Шаг 2: Тестирование API"""
    print_section("ШАГ 2: Тестирование подключения к YClients API", "🔌")
    
    try:
        api = get_yclients_api()
        print("✅ API клиент создан")
        
        # Тест 1: Получение мастеров
        print("\n📋 Тест 1: Получение списка мастеров...")
        staff_list = api.get_staff()
        
        if staff_list:
            print(f"✅ Получено мастеров: {len(staff_list)}")
            print("\nМастера из YClients:")
            for idx, staff in enumerate(staff_list, 1):
                print(f"   {idx}. {staff.get('name')} (ID: {staff.get('id')})")
        else:
            print("❌ Не удалось получить мастеров!")
            return False
        
        # Тест 2: Получение услуг первого мастера
        if staff_list:
            first_staff = staff_list[0]
            staff_id = first_staff.get('id')
            staff_name = first_staff.get('name')
            
            print(f"\n📋 Тест 2: Получение услуг мастера '{staff_name}'...")
            services = api.get_staff_services(staff_id)
            
            if services:
                print(f"✅ Получено услуг: {len(services)}")
                print(f"\nПервые 3 услуги:")
                for idx, service in enumerate(services[:3], 1):
                    print(f"   {idx}. {service.get('title')} (ID: {service.get('id')})")
            else:
                print("⚠️ У мастера нет услуг")
        
        print("\n✅ API работает корректно!")
        return True
        
    except YClientsAPIError as e:
        print(f"\n❌ Ошибка API: {e}")
        return False
    except Exception as e:
        print(f"\n❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return False


def step3_sync_masters():
    """Шаг 3: Синхронизация мастеров"""
    print_section("ШАГ 3: Синхронизация мастеров из YClients", "🔄")
    
    try:
        api = get_yclients_api()
        
        # Получаем мастеров из YClients
        print("📥 Получаем мастеров из YClients...")
        staff_list = api.get_staff()
        
        if not staff_list:
            print("❌ Не удалось получить мастеров!")
            return False
        
        print(f"✅ Получено мастеров: {len(staff_list)}")
        
        # Синхронизируем каждого мастера
        created = 0
        updated = 0
        
        for staff_data in staff_list:
            staff_id = staff_data.get('id')
            staff_name = staff_data.get('name')
            
            # Ищем или создаём мастера
            master, is_created = Master.objects.get_or_create(
                id=staff_id,
                defaults={
                    'name': staff_name,
                    'is_active': True
                }
            )
            
            if is_created:
                created += 1
                print(f"   ➕ Создан: {staff_name}")
            else:
                # Обновляем имя если изменилось
                if master.name != staff_name:
                    master.name = staff_name
                    master.save()
                    updated += 1
                    print(f"   ✏️ Обновлён: {staff_name}")
        
        print(f"\n✅ Создано мастеров: {created}")
        print(f"✅ Обновлено мастеров: {updated}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка синхронизации: {e}")
        import traceback
        traceback.print_exc()
        return False


def step4_sync_services():
    """Шаг 4: Синхронизация услуг мастеров"""
    print_section("ШАГ 4: Синхронизация услуг мастеров", "🔗")
    
    try:
        api = get_yclients_api()
        
        # Получаем всех мастеров из БД
        masters = Master.objects.filter(is_active=True)
        
        print(f"📋 Обрабатываем {masters.count()} мастеров...")
        
        total_services_added = 0
        
        for master in masters:
            print(f"\n👤 {master.name} (ID: {master.id})")
            
            # Получаем услуги мастера из YClients
            yclients_services = api.get_staff_services(master.id)
            
            if not yclients_services:
                print(f"   ⚠️ Нет услуг в YClients")
                continue
            
            print(f"   📥 Получено услуг из YClients: {len(yclients_services)}")
            
            # Синхронизируем услуги
            services_to_add = set()
            not_found = 0
            
            for service_data in yclients_services:
                yclients_id = str(service_data.get('id'))
                service_title = service_data.get('title', 'Без названия')
                
                # Ищем Service в Django по yclients_service_id
                # Используем filter().first() т.к. может быть несколько вариантов одной услуги
                option = ServiceOption.objects.filter(
                    yclients_service_id=yclients_id,
                    is_active=True
                ).first()
                
                if option:
                    services_to_add.add(option.service)
                else:
                    not_found += 1
                    if not_found <= 3:  # Показываем первые 3
                        print(f"   ⚠️ Не найдена: {service_title} (YClients ID: {yclients_id})")
            
            if not_found > 3:
                print(f"   ⚠️ ... и ещё {not_found - 3} не найдено")
            
            # Добавляем услуги к мастеру
            if services_to_add:
                current_services = set(master.services.all())
                new_services = services_to_add - current_services
                
                if new_services:
                    master.services.add(*new_services)
                    total_services_added += len(new_services)
                    print(f"   ➕ Добавлено услуг: {len(new_services)}")
                else:
                    print(f"   ℹ️ Все услуги уже добавлены ({len(services_to_add)} шт)")
        
        print(f"\n✅ Всего добавлено связей: {total_services_added}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка синхронизации услуг: {e}")
        import traceback
        traceback.print_exc()
        return False


def step5_show_results():
    """Шаг 5: Показать результаты"""
    print_section("ШАГ 5: Результаты синхронизации", "📊")
    
    masters = Master.objects.filter(is_active=True)
    
    print(f"👥 Активных мастеров в БД: {masters.count()}")
    
    if masters.count() == 0:
        print("❌ Нет мастеров в БД!")
        return False
    
    print("\n📋 Детали по мастерам:")
    
    total_links = 0
    
    for master in masters:
        services_count = master.services.count()
        total_links += services_count
        
        icon = "✅" if services_count > 0 else "⚠️"
        print(f"\n{icon} {master.name}")
        print(f"   Услуг: {services_count}")
        
        if services_count > 0:
            for idx, service in enumerate(master.services.all()[:3], 1):
                print(f"   {idx}. {service.name}")
            
            if services_count > 3:
                print(f"   ... и ещё {services_count - 3} услуг")
    
    print(f"\n📊 Всего связей Мастер ↔ Услуга: {total_links}")
    
    if total_links > 0:
        print("\n✅ Синхронизация успешна!")
        return True
    else:
        print("\n⚠️ Связи не созданы")
        return False


def main():
    """Главная функция"""
    print("\n" + "🔬 ДИАГНОСТИКА И СИНХРОНИЗАЦИЯ YCLIENTS" + "\n")
    
    results = []
    
    # Шаг 1: Проверка настроек
    if not step1_check_settings():
        print("\n❌ Остановлено: проверь .env файл")
        return
    results.append(True)
    
    # Шаг 2: Тестирование API
    if not step2_test_api_connection():
        print("\n❌ Остановлено: API не работает")
        return
    results.append(True)
    
    # Шаг 3: Синхронизация мастеров
    if not step3_sync_masters():
        print("\n❌ Остановлено: не удалось синхронизировать мастеров")
        return
    results.append(True)
    
    # Шаг 4: Синхронизация услуг
    if not step4_sync_services():
        print("\n❌ Остановлено: не удалось синхронизировать услуги")
        return
    results.append(True)
    
    # Шаг 5: Результаты
    if not step5_show_results():
        print("\n⚠️ Синхронизация завершена с предупреждениями")
    results.append(True)
    
    # Итоги
    print_section("ИТОГИ", "🎉")
    
    if all(results):
        print("""
    ✅ Все шаги выполнены успешно!
    
    Что дальше:
    1. Запусти: python test_master_service_links.py
    2. Проверь Django Admin: /admin/services_app/master/
    3. Проверь фильтрацию на сайте
        """)
    else:
        print("\n⚠️ Некоторые шаги не выполнены")
    
    print("="*70 + "\n")


if __name__ == '__main__':
    main()