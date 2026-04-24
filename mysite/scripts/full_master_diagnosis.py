#!/usr/bin/env python
"""
ПОЛНАЯ диагностика услуг мастера: YClients vs Django

ПРАВИЛЬНАЯ ЛОГИКА:
- В YClients: 1 услуга = 1 ID (независимо от вариантов)
- В Django: 1 Service может иметь много ServiceOption с одним yclients_service_id
- ПРАВИЛО: YClients ID → находим ЛЮБОЙ ServiceOption → берём его Service

Запуск:
    python full_master_diagnosis.py
    python full_master_diagnosis.py "Инна Сазанова"
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
from collections import defaultdict


def print_section(title: str, emoji: str = "📋"):
    """Красивый заголовок"""
    print("\n" + "="*70)
    print(f"{emoji} {title}")
    print("="*70)


def analyze_master(master_name: str = "Денис Архипкин"):
    """
    Полный анализ услуг мастера
    """
    print_section(f"МАСТЕР: {master_name}", "👤")
    
    # 1. Ищем мастера в БД
    try:
        master = Master.objects.get(name__icontains=master_name)
        print(f"✅ Найден: {master.name} (ID: {master.id})")
    except Master.DoesNotExist:
        print(f"❌ Мастер '{master_name}' не найден в Django БД!")
        return
    except Master.MultipleObjectsReturned:
        masters = Master.objects.filter(name__icontains=master_name)
        master = masters.first()
        print(f"⚠️ Найдено несколько, используем: {master.name}")
    
    # 2. Получаем услуги из YClients
    print_section("ШАГ 1: Получение услуг из YClients API", "📥")
    
    api = get_yclients_api()
    yclients_services = api.get_staff_services(master.id)
    
    print(f"📊 Получено услуг из YClients: {len(yclients_services)}")
    
    if not yclients_services:
        print("⚠️ У мастера нет услуг в YClients")
        return
    
    # Показываем первые 5
    print("\nПервые 5 услуг:")
    for idx, svc in enumerate(yclients_services[:5], 1):
        print(f"{idx}. {svc.get('title')} (ID: {svc.get('id')})")
    
    if len(yclients_services) > 5:
        print(f"... и ещё {len(yclients_services) - 5}")
    
    # 3. Анализируем сопоставление YClients → Django
    print_section("ШАГ 2: Сопоставление YClients → Django", "🔍")
    
    mapping = []  # Результаты сопоставления
    
    for yclients_svc in yclients_services:
        yclients_id = str(yclients_svc.get('id'))
        yclients_title = yclients_svc.get('title', 'Без названия')
        
        # Ищем ВСЕ ServiceOption с этим yclients_service_id
        options = ServiceOption.objects.filter(
            yclients_service_id=yclients_id,
            is_active=True
        ).select_related('service')
        
        result = {
            'yclients_id': yclients_id,
            'yclients_title': yclients_title,
            'options_count': options.count(),
            'options': list(options),
            'service': None,
            'status': None
        }
        
        if options.exists():
            # Берём Service из первого найденного варианта
            # (все варианты должны указывать на одну Service)
            result['service'] = options.first().service
            result['status'] = 'found'
            
            # Проверяем что все варианты указывают на одну Service
            unique_services = set(opt.service for opt in options)
            if len(unique_services) > 1:
                result['status'] = 'conflict'
                result['unique_services'] = unique_services
        else:
            result['status'] = 'not_found'
        
        mapping.append(result)
    
    # 4. Статистика
    print_section("ШАГ 3: Результаты сопоставления", "📊")
    
    found = [m for m in mapping if m['status'] == 'found']
    not_found = [m for m in mapping if m['status'] == 'not_found']
    conflicts = [m for m in mapping if m['status'] == 'conflict']
    
    print(f"""
    📊 Статистика сопоставления:
    
       Всего услуг в YClients:     {len(yclients_services)}
       
       ✅ Найдено в Django:         {len(found)}
       ❌ Не найдено в Django:      {len(not_found)}
       ⚠️ Конфликты (разные Service): {len(conflicts)}
    """)
    
    # Подробности по найденным
    if found:
        print_section("✅ НАЙДЕННЫЕ УСЛУГИ", "✅")
        print(f"Всего: {len(found)}\n")
        
        # Группируем по количеству вариантов
        by_variants = defaultdict(list)
        for item in found:
            by_variants[item['options_count']].append(item)
        
        print("📊 Распределение по вариантам:")
        for count in sorted(by_variants.keys()):
            items = by_variants[count]
            print(f"   {count} вариант(ов): {len(items)} услуг")
        
        print("\n📋 Детали (первые 10):")
        for idx, item in enumerate(found[:10], 1):
            print(f"\n{idx}. {item['yclients_title']}")
            print(f"   YClients ID: {item['yclients_id']}")
            print(f"   Django Service: {item['service'].name}")
            print(f"   Вариантов (ServiceOption): {item['options_count']}")
            
            if item['options_count'] > 1:
                print(f"   Варианты:")
                for opt in item['options'][:3]:
                    print(f"      • {opt.duration_min} мин, "
                          f"{opt.units} {opt.get_unit_type_display()}, "
                          f"{opt.price} ₽")
                if item['options_count'] > 3:
                    print(f"      ... и ещё {item['options_count'] - 3}")
        
        if len(found) > 10:
            print(f"\n   ... и ещё {len(found) - 10} услуг")
    
    # Подробности по НЕ найденным
    if not_found:
        print_section("❌ НЕ НАЙДЕННЫЕ УСЛУГИ", "❌")
        print(f"Всего: {len(not_found)}\n")
        print("Эти услуги есть в YClients, но НЕТ в Django БД:")
        print("(нужно создать ServiceOption с указанием yclients_service_id)\n")
        
        for idx, item in enumerate(not_found, 1):
            print(f"{idx}. {item['yclients_title']}")
            print(f"   YClients ID: {item['yclients_id']}")
            print()
    
    # Подробности по конфликтам
    if conflicts:
        print_section("⚠️ КОНФЛИКТЫ", "⚠️")
        print(f"Всего: {len(conflicts)}\n")
        print("Варианты услуги указывают на РАЗНЫЕ Service (это ошибка!):\n")
        
        for idx, item in enumerate(conflicts, 1):
            print(f"{idx}. {item['yclients_title']}")
            print(f"   YClients ID: {item['yclients_id']}")
            print(f"   Найдено разных Service: {len(item['unique_services'])}")
            for svc in item['unique_services']:
                print(f"      • {svc.name}")
            print()
    
    # 5. Проверяем текущие связи мастера
    print_section("ШАГ 4: Текущие связи Master ↔ Service в БД", "🔗")
    
    current_services = set(master.services.filter(is_active=True))
    expected_services = set(item['service'] for item in found if item['service'])
    
    print(f"Текущих связей: {len(current_services)}")
    print(f"Ожидается связей: {len(expected_services)}")
    
    missing = expected_services - current_services
    extra = current_services - expected_services
    
    if missing:
        print(f"\n⚠️ НЕ ХВАТАЕТ связей ({len(missing)}):")
        for svc in list(missing)[:10]:
            print(f"   - {svc.name}")
        if len(missing) > 10:
            print(f"   ... и ещё {len(missing) - 10}")
    
    if extra:
        print(f"\n⚠️ ЛИШНИЕ связи ({len(extra)}):")
        for svc in list(extra)[:10]:
            print(f"   - {svc.name}")
        if len(extra) > 10:
            print(f"   ... и ещё {len(extra) - 10}")
    
    if not missing and not extra:
        print("\n✅ Все связи корректны!")
    
    # 6. Рекомендации
    print_section("РЕКОМЕНДАЦИИ", "💡")
    
    if not_found:
        print(f"""
    ❌ {len(not_found)} услуг НЕ НАЙДЕНЫ в Django БД
    
    РЕШЕНИЕ:
    1. Открой Django Admin: /admin/services_app/serviceoption/add/
    2. Создай ServiceOption для каждой услуги:
        """)
        for item in not_found[:5]:
            print(f"   • {item['yclients_title']}")
            print(f"     yclients_service_id = {item['yclients_id']}")
        if len(not_found) > 5:
            print(f"   ... и ещё {len(not_found) - 5}")
        print()
    
    if conflicts:
        print(f"""
    ⚠️ {len(conflicts)} услуг имеют КОНФЛИКТЫ
    
    РЕШЕНИЕ:
    1. Открой Django Admin: /admin/services_app/serviceoption/
    2. Найди ServiceOption с конфликтующими yclients_service_id
    3. Убедись что все варианты одной услуги указывают на одну Service
        """)
    
    if missing:
        print(f"""
    🔄 {len(missing)} услуг найдены, но НЕ ПРИВЯЗАНЫ к мастеру
    
    РЕШЕНИЕ:
    Запусти синхронизацию:
        python diagnose_and_sync.py
        """)
    
    if not not_found and not conflicts and not missing:
        print("""
    ✅ ВСЁ ОТЛИЧНО!
    
    Все услуги из YClients найдены в Django и правильно привязаны к мастеру.
        """)
    
    # 7. Детальная таблица соответствий
    print_section("ПОЛНАЯ ТАБЛИЦА СООТВЕТСТВИЙ", "📋")
    
    print(f"\n{'№':<4} {'YClients ID':<12} {'Опций':<6} {'Статус':<10} {'Название'}")
    print("-" * 80)
    
    for idx, item in enumerate(mapping, 1):
        status_icon = {
            'found': '✅',
            'not_found': '❌',
            'conflict': '⚠️'
        }.get(item['status'], '?')
        
        print(f"{idx:<4} {item['yclients_id']:<12} "
              f"{item['options_count']:<6} "
              f"{status_icon:<10} "
              f"{item['yclients_title'][:50]}")
    
    return {
        'total': len(yclients_services),
        'found': len(found),
        'not_found': len(not_found),
        'conflicts': len(conflicts),
        'missing_links': len(missing)
    }


def compare_all_masters():
    """
    Сравнить всех мастеров
    """
    print_section("СРАВНЕНИЕ ВСЕХ МАСТЕРОВ", "👥")
    
    masters = Master.objects.filter(is_active=True)
    
    results = []
    
    for master in masters:
        print(f"\n📌 {master.name}...", end=" ")
        
        try:
            api = get_yclients_api()
            yclients_services = api.get_staff_services(master.id)
            
            found = 0
            not_found = 0
            
            for svc in yclients_services:
                yclients_id = str(svc.get('id'))
                options = ServiceOption.objects.filter(
                    yclients_service_id=yclients_id,
                    is_active=True
                )
                
                if options.exists():
                    found += 1
                else:
                    not_found += 1
            
            current_links = master.services.filter(is_active=True).count()
            
            results.append({
                'master': master,
                'yclients_total': len(yclients_services),
                'found': found,
                'not_found': not_found,
                'current_links': current_links
            })
            
            print(f"YC:{len(yclients_services)} Found:{found} Missing:{not_found} Links:{current_links}")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
    
    # Итоговая таблица
    print_section("ИТОГОВАЯ ТАБЛИЦА", "📊")
    
    print(f"\n{'Мастер':<25} {'YClients':<10} {'Найдено':<10} {'Не найд.':<10} {'Связей':<10}")
    print("-" * 75)
    
    for r in results:
        status = "✅" if r['not_found'] == 0 else "⚠️"
        print(f"{status} {r['master'].name:<23} "
              f"{r['yclients_total']:<10} "
              f"{r['found']:<10} "
              f"{r['not_found']:<10} "
              f"{r['current_links']:<10}")
    
    total_missing = sum(r['not_found'] for r in results)
    
    if total_missing > 0:
        print(f"\n⚠️ Всего не найдено услуг: {total_missing}")
    else:
        print(f"\n✅ Все услуги найдены!")


def main():
    """Главная функция"""
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--all":
            compare_all_masters()
        else:
            master_name = " ".join(sys.argv[1:])
            analyze_master(master_name)
    else:
        analyze_master("Денис Архипкин")
    
    print("\n" + "="*70 + "\n")


if __name__ == '__main__':
    main()