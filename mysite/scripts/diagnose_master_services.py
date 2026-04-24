#!/usr/bin/env python
"""
Диагностика услуг конкретного мастера

Что проверяет:
1. Получает услуги мастера из YClients API
2. Сравнивает с услугами в Django БД
3. Показывает какие услуги не найдены и почему

Запуск:
    python diagnose_master_services.py
"""

import os
import sys
import django

# Настройка Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mysite'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings.dev')
django.setup()

from services_app.yclients_api import get_yclients_api
from services_app.models import Master, Service, ServiceOption


def print_section(title: str, emoji: str = "📋"):
    """Красивый заголовок"""
    print("\n" + "="*70)
    print(f"{emoji} {title}")
    print("="*70)


def diagnose_master(master_name: str = "Денис Архипкин"):
    """
    Диагностика услуг конкретного мастера
    """
    print_section(f"ДИАГНОСТИКА МАСТЕРА: {master_name}", "🔍")
    
    # Ищем мастера в БД
    try:
        master = Master.objects.get(name__icontains=master_name)
        print(f"✅ Мастер найден в БД:")
        print(f"   ID: {master.id}")
        print(f"   Имя: {master.name}")
        print(f"   Активен: {master.is_active}")
    except Master.DoesNotExist:
        print(f"❌ Мастер '{master_name}' не найден в БД!")
        return
    except Master.MultipleObjectsReturned:
        print(f"⚠️ Найдено несколько мастеров с именем '{master_name}'")
        masters = Master.objects.filter(name__icontains=master_name)
        for m in masters:
            print(f"   - {m.name} (ID: {m.id})")
        master = masters.first()
        print(f"\n📌 Используем первого: {master.name}")
    
    # Получаем услуги из YClients
    print_section("ШАГ 1: Услуги из YClients API", "📥")
    
    api = get_yclients_api()
    yclients_services = api.get_staff_services(master.id)
    
    print(f"✅ Получено услуг из YClients: {len(yclients_services)}")
    
    if not yclients_services:
        print("⚠️ Нет услуг в YClients для этого мастера")
        return
    
    # Анализируем каждую услугу
    print_section("ШАГ 2: Анализ каждой услуги", "🔍")
    
    found = []
    not_found = []
    duplicates = []
    
    for idx, service_data in enumerate(yclients_services, 1):
        yclients_id = str(service_data.get('id'))
        title = service_data.get('title', 'Без названия')
        
        # Ищем в Django
        options = ServiceOption.objects.filter(
            yclients_service_id=yclients_id,
            is_active=True
        )
        
        count = options.count()
        
        if count == 0:
            not_found.append({
                'id': yclients_id,
                'title': title,
                'reason': 'Не найдено в БД'
            })
        elif count == 1:
            option = options.first()
            found.append({
                'id': yclients_id,
                'title': title,
                'option': option,
                'service': option.service
            })
        else:  # count > 1
            duplicates.append({
                'id': yclients_id,
                'title': title,
                'count': count,
                'options': list(options)
            })
    
    # РЕЗУЛЬТАТЫ
    print_section("ШАГ 3: Результаты анализа", "📊")
    
    print(f"""
    📊 Статистика:
       Всего услуг в YClients: {len(yclients_services)}
       
       ✅ Найдено в Django: {len(found)}
       ⚠️ Дубликаты (2+ варианта): {len(duplicates)}
       ❌ Не найдено в БД: {len(not_found)}
    """)
    
    # НАЙДЕННЫЕ
    if found:
        print_section("✅ НАЙДЕННЫЕ УСЛУГИ", "✅")
        for item in found[:10]:
            print(f"✅ {item['title']}")
            print(f"   YClients ID: {item['id']}")
            print(f"   Django Service: {item['service'].name}")
            print(f"   Django Option: {item['option']}")
        
        if len(found) > 10:
            print(f"\n   ... и ещё {len(found) - 10} услуг")
    
    # ДУБЛИКАТЫ
    if duplicates:
        print_section("⚠️ ДУБЛИКАТЫ (несколько вариантов одной услуги)", "⚠️")
        for item in duplicates:
            print(f"\n⚠️ {item['title']}")
            print(f"   YClients ID: {item['id']}")
            print(f"   Найдено вариантов: {item['count']}")
            
            for idx, option in enumerate(item['options'], 1):
                print(f"   {idx}. {option}")
                print(f"      Service: {option.service.name}")
                print(f"      Duration: {option.duration_min} мин")
                print(f"      Units: {option.units} {option.get_unit_type_display()}")
                print(f"      Price: {option.price} ₽")
    
    # НЕ НАЙДЕННЫЕ
    if not_found:
        print_section("❌ НЕ НАЙДЕННЫЕ УСЛУГИ", "❌")
        print(f"\nЭти услуги есть в YClients, но НЕТ в Django БД:")
        print(f"(Нужно добавить в Django Admin с правильным yclients_service_id)\n")
        
        for item in not_found:
            print(f"❌ {item['title']}")
            print(f"   YClients ID: {item['id']}")
            print(f"   Причина: {item['reason']}")
            print()
    
    # ТЕКУЩИЕ УСЛУГИ МАСТЕРА В DJANGO
    print_section("ШАГ 4: Текущие услуги мастера в Django БД", "📋")
    
    current_services = master.services.filter(is_active=True)
    print(f"Услуг в БД: {current_services.count()}")
    
    if current_services.exists():
        print("\nСписок услуг:")
        for idx, service in enumerate(current_services, 1):
            # Находим ServiceOption для этой услуги
            options = ServiceOption.objects.filter(
                service=service,
                is_active=True
            )
            
            yclients_ids = [opt.yclients_service_id for opt in options if opt.yclients_service_id]
            
            print(f"{idx}. {service.name}")
            if yclients_ids:
                print(f"   YClients IDs: {', '.join(yclients_ids)}")
            else:
                print(f"   YClients ID: Не указан")
    
    # РЕКОМЕНДАЦИИ
    print_section("РЕКОМЕНДАЦИИ", "💡")
    
    if not_found:
        print(f"""
    ❌ Найдено {len(not_found)} услуг которых НЕТ в Django БД
    
    Что делать:
    1. Открой Django Admin: /admin/services_app/serviceoption/
    2. Найди услуги мастера "{master.name}"
    3. Проверь что у них указан yclients_service_id
    4. Добавь недостающие услуги:
        """)
        
        for item in not_found[:5]:
            print(f"   - {item['title']} (YClients ID: {item['id']})")
        
        if len(not_found) > 5:
            print(f"   ... и ещё {len(not_found) - 5} услуг")
    
    if duplicates:
        print(f"""
    ⚠️ Найдено {len(duplicates)} услуг с несколькими вариантами
    
    Это НОРМАЛЬНО если:
    - Разные длительности (60 мин, 90 мин)
    - Разные пакеты (1 процедура, 5 процедур)
    - Разные зоны (1 зона, 3 зоны)
    
    Скрипт синхронизации берёт ПЕРВЫЙ вариант каждой услуги.
        """)
    
    if len(found) == len(yclients_services):
        print(f"""
    ✅ ВСЕ УСЛУГИ НАЙДЕНЫ!
    
    Мастер "{master.name}" должен иметь {len(found)} услуг.
    Запусти синхронизацию повторно:
        python diagnose_and_sync.py
        """)
    
    # ПРОВЕРКА СВЯЗЕЙ В БД
    print_section("ШАГ 5: Проверка связей Master ↔ Service", "🔗")
    
    expected_services = set()
    for item in found + duplicates:
        if 'service' in item:
            expected_services.add(item['service'])
        elif 'options' in item:
            for opt in item['options']:
                expected_services.add(opt.service)
    
    current_services_set = set(master.services.filter(is_active=True))
    
    missing = expected_services - current_services_set
    extra = current_services_set - expected_services
    
    print(f"Ожидается услуг: {len(expected_services)}")
    print(f"Текущих услуг: {len(current_services_set)}")
    
    if missing:
        print(f"\n⚠️ Не хватает услуг ({len(missing)}):")
        for service in list(missing)[:5]:
            print(f"   - {service.name}")
        if len(missing) > 5:
            print(f"   ... и ещё {len(missing) - 5}")
    
    if extra:
        print(f"\n⚠️ Лишние услуги ({len(extra)}):")
        for service in list(extra)[:5]:
            print(f"   - {service.name}")
        if len(extra) > 5:
            print(f"   ... и ещё {len(extra) - 5}")
    
    if not missing and not extra:
        print("\n✅ Все связи корректны!")


def main():
    """Главная функция"""
    print("\n" + "🔬 ДИАГНОСТИКА УСЛУГ МАСТЕРА" + "\n")
    
    # Можно указать другого мастера
    import sys
    if len(sys.argv) > 1:
        master_name = " ".join(sys.argv[1:])
    else:
        master_name = "Денис Архипкин"
    
    diagnose_master(master_name)
    
    print("\n" + "="*70 + "\n")


if __name__ == '__main__':
    main()