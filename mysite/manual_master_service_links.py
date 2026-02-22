#!/usr/bin/env python
"""
Тестовый скрипт проверки связей Мастер ↔ Услуга после синхронизации

Что проверяет:
1. Количество мастеров в БД
2. Количество услуг у каждого мастера
3. Обратную связь: услуга → мастера
4. Реальный пример фильтрации для сайта

Запуск:
    python test_master_service_links.py
"""

import os
import sys
import django

# Настройка Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mysite'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings.dev')
django.setup()

from services_app.models import Master, Service, ServiceOption
from django.db.models import Count


def print_section(title: str, emoji: str = "📋"):
    """Красивый заголовок"""
    print("\n" + "="*70)
    print(f"{emoji} {title}")
    print("="*70)


def test_masters_count():
    """Тест 1: Проверка количества мастеров"""
    print_section("ТЕСТ 1: Количество мастеров", "👥")
    
    total = Master.objects.count()
    active = Master.objects.filter(is_active=True).count()
    
    print(f"Всего мастеров: {total}")
    print(f"Активных мастеров: {active}")
    
    if active == 0:
        print("❌ ОШИБКА: Нет активных мастеров!")
        return False
    
    print("✅ Мастера есть в БД")
    return True


def test_masters_with_services():
    """Тест 2: Мастера с услугами"""
    print_section("ТЕСТ 2: Мастера с услугами", "🔗")
    
    # Мастера с услугами
    masters_with_services = Master.objects.filter(
        is_active=True,
        services__isnull=False
    ).distinct()
    
    # Мастера БЕЗ услуг
    masters_without_services = Master.objects.filter(
        is_active=True,
        services__isnull=True
    )
    
    print(f"✅ Мастеров с услугами: {masters_with_services.count()}")
    print(f"⚠️ Мастеров БЕЗ услуг: {masters_without_services.count()}")
    
    if masters_without_services.exists():
        print("\n⚠️ Мастера БЕЗ услуг:")
        for master in masters_without_services:
            print(f"   - {master.name} (ID: {master.id})")
    
    return masters_with_services.count() > 0


def test_each_master_services():
    """Тест 3: Детали по каждому мастеру"""
    print_section("ТЕСТ 3: Услуги каждого мастера", "📋")
    
    masters = Master.objects.filter(is_active=True).prefetch_related('services')
    
    total_links = 0
    
    for master in masters:
        services_count = master.services.count()
        total_links += services_count
        
        icon = "✅" if services_count > 0 else "⚠️"
        print(f"\n{icon} {master.name} (ID: {master.id})")
        print(f"   Услуг: {services_count}")
        
        if services_count > 0:
            # Показываем первые 5 услуг
            for idx, service in enumerate(master.services.all()[:5], 1):
                print(f"   {idx}. {service.name}")
            
            if services_count > 5:
                print(f"   ... и ещё {services_count - 5} услуг")
    
    print(f"\n📊 Всего связей Мастер ↔ Услуга: {total_links}")
    
    return total_links > 0


def test_service_to_masters():
    """Тест 4: Обратная связь - услуга → мастера"""
    print_section("ТЕСТ 4: Обратная связь Услуга → Мастера", "🔄")
    
    # Берём первые 5 услуг с мастерами
    services = Service.objects.filter(
        is_active=True,
        masters__isnull=False
    ).distinct().prefetch_related('masters')[:5]
    
    if not services.exists():
        print("❌ ОШИБКА: Нет услуг с привязанными мастерами!")
        return False
    
    for service in services:
        masters = service.masters.filter(is_active=True)
        print(f"\n📌 {service.name}")
        print(f"   Мастеров: {masters.count()}")
        
        for master in masters:
            print(f"   ├─ {master.name}")
    
    print("\n✅ Обратная связь работает!")
    return True


def test_real_filtering_scenario():
    """Тест 5: Реальный сценарий фильтрации для сайта"""
    print_section("ТЕСТ 5: Реальный сценарий для сайта", "🎯")
    
    # Берём первую услугу с yclients_service_id
    option = ServiceOption.objects.filter(
        is_active=True,
        yclients_service_id__isnull=False
    ).select_related('service').first()
    
    if not option:
        print("⚠️ Нет ServiceOption с yclients_service_id")
        return False
    
    service = option.service
    
    print(f"\n📌 Сценарий: Пользователь выбрал услугу")
    print(f"   Услуга: {service.name}")
    print(f"   ServiceOption ID: {option.id}")
    print(f"   YClients Service ID: {option.yclients_service_id}")
    
    # Получаем мастеров для этой услуги
    masters = service.masters.filter(is_active=True)
    
    print(f"\n📋 Доступные мастера для этой услуги:")
    print(f"   Найдено мастеров: {masters.count()}")
    
    if masters.exists():
        for master in masters:
            print(f"   ✅ {master.name} (ID: {master.id})")
        
        print(f"\n✅ Фильтрация работает правильно!")
        print(f"   Пользователь увидит {masters.count()} мастер(а)")
        return True
    else:
        print(f"\n❌ ПРОБЛЕМА: Нет мастеров для услуги '{service.name}'")
        print(f"   Проверь синхронизацию!")
        return False


def test_statistics():
    """Тест 6: Общая статистика"""
    print_section("ТЕСТ 6: Общая статистика БД", "📊")
    
    # Мастера
    total_masters = Master.objects.filter(is_active=True).count()
    masters_with_services = Master.objects.filter(
        is_active=True,
        services__isnull=False
    ).distinct().count()
    
    # Услуги
    total_services = Service.objects.filter(is_active=True).count()
    services_with_masters = Service.objects.filter(
        is_active=True,
        masters__isnull=False
    ).distinct().count()
    
    # ServiceOptions с YClients ID
    options_with_yclients = ServiceOption.objects.filter(
        is_active=True,
        yclients_service_id__isnull=False
    ).count()
    
    # Общее количество связей
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) 
            FROM services_app_service_masters
        """)
        total_links = cursor.fetchone()[0]
    
    print(f"""
    👥 Мастера:
       Всего активных: {total_masters}
       С услугами: {masters_with_services}
       БЕЗ услуг: {total_masters - masters_with_services}
    
    📋 Услуги:
       Всего активных: {total_services}
       С мастерами: {services_with_masters}
       БЕЗ мастеров: {total_services - services_with_masters}
    
    🔗 ServiceOptions:
       С YClients ID: {options_with_yclients}
    
    📊 Связи:
       Всего связей Мастер ↔ Услуга: {total_links}
    """)
    
    # Проверка качества данных
    coverage = (masters_with_services / total_masters * 100) if total_masters > 0 else 0
    
    print(f"    📈 Покрытие: {coverage:.1f}% мастеров имеют услуги")
    
    if coverage >= 80:
        print("    ✅ Отличное покрытие!")
    elif coverage >= 50:
        print("    ⚠️ Среднее покрытие, можно улучшить")
    else:
        print("    ❌ Низкое покрытие, нужна синхронизация!")
    
    return True


def test_specific_master_services(master_name: str = None):
    """Тест 7: Услуги конкретного мастера (опционально)"""
    if not master_name:
        # Берём первого мастера
        master = Master.objects.filter(
            is_active=True,
            services__isnull=False
        ).first()
    else:
        master = Master.objects.filter(name__icontains=master_name).first()
    
    if not master:
        print("⚠️ Мастер не найден")
        return False
    
    print_section(f"ТЕСТ 7: Услуги мастера '{master.name}'", "🔍")
    
    services = master.services.filter(is_active=True)
    
    print(f"Всего услуг: {services.count()}")
    print(f"\nСписок услуг:")
    
    for idx, service in enumerate(services, 1):
        # Находим ServiceOption для этой услуги
        option = ServiceOption.objects.filter(
            service=service,
            is_active=True
        ).first()
        
        yclients_id = option.yclients_service_id if option else "Нет"
        
        print(f"{idx}. {service.name}")
        print(f"   YClients ID: {yclients_id}")
    
    return True


def main():
    """Главная функция"""
    print("\n" + "🧪 ТЕСТИРОВАНИЕ СВЯЗЕЙ МАСТЕР ↔ УСЛУГА" + "\n")
    
    results = []
    
    # Запускаем все тесты
    results.append(("Количество мастеров", test_masters_count()))
    results.append(("Мастера с услугами", test_masters_with_services()))
    results.append(("Услуги каждого мастера", test_each_master_services()))
    results.append(("Обратная связь", test_service_to_masters()))
    results.append(("Реальный сценарий", test_real_filtering_scenario()))
    results.append(("Статистика", test_statistics()))
    results.append(("Конкретный мастер", test_specific_master_services()))
    
    # Итоги
    print_section("ИТОГИ ТЕСТИРОВАНИЯ", "✅")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"\nПройдено тестов: {passed}/{total}")
    print("")
    
    for test_name, result in results:
        icon = "✅" if result else "❌"
        print(f"{icon} {test_name}")
    
    if passed == total:
        print(f"\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        print(f"\n✅ Связи Мастер ↔ Услуга работают правильно!")
        print(f"✅ Фильтрация на сайте будет работать!")
    elif passed >= total * 0.7:
        print(f"\n⚠️ Большинство тестов пройдено")
        print(f"💡 Рекомендуется запустить повторную синхронизацию")
    else:
        print(f"\n❌ ПРОБЛЕМЫ С ДАННЫМИ!")
        print(f"🔧 Нужно запустить синхронизацию:")
        print(f"   python sync_masters_services_from_yclients.py")
    
    print("\n" + "="*70 + "\n")


if __name__ == '__main__':
    main()