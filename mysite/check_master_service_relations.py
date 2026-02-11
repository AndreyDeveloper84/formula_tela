#!/usr/bin/env python
"""
Скрипт для проверки связей Master ↔ Service ↔ ServiceOption
Запуск: python check_master_service_relations.py
"""

import os
import sys
import django

# Настройка Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mysite'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings.dev')
django.setup()

from services_app.models import Service, ServiceOption, Master


def print_section(title):
    """Красивый заголовок секции"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def check_database_structure():
    """Проверка структуры БД"""
    print_section("ПРОВЕРКА СТРУКТУРЫ БД")
    
    services_count = Service.objects.filter(is_active=True).count()
    options_count = ServiceOption.objects.filter(is_active=True).count()
    masters_count = Master.objects.filter(is_active=True).count()
    
    print(f"✅ Активных услуг (Service): {services_count}")
    print(f"✅ Активных вариантов (ServiceOption): {options_count}")
    print(f"✅ Активных мастеров (Master): {masters_count}")
    
    return services_count > 0 and masters_count > 0


def check_masters_services():
    """Проверка связей мастеров и услуг"""
    print_section("СВЯЗИ МАСТЕРОВ И УСЛУГ")
    
    masters = Master.objects.filter(is_active=True).prefetch_related('services')
    
    for master in masters:
        services = master.services.all()
        print(f"\n👤 {master.name} (ID: {master.id})")
        print(f"   Делает услуг: {services.count()}")
        
        for service in services:
            options_count = service.options.filter(is_active=True).count()
            print(f"   ├─ {service.name} ({options_count} вариантов)")


def check_services_masters():
    """Проверка связей услуг и мастеров (обратная связь)"""
    print_section("УСЛУГИ И ИХ МАСТЕРА")
    
    services = Service.objects.filter(is_active=True).prefetch_related('masters', 'options')
    
    for service in services:
        masters = service.masters.filter(is_active=True)
        options = service.options.filter(is_active=True)
        
        print(f"\n💼 {service.name} (ID: {service.id})")
        print(f"   Вариантов: {options.count()}")
        print(f"   Мастеров: {masters.count()}")
        
        for master in masters:
            print(f"   ├─ {master.name}")
        
        print(f"\n   Варианты услуги:")
        for option in options:
            yclients_id = option.yclients_service_id or 'нет ID'
            print(f"   ├─ {option.duration_min} мин — {option.price}₽ (YClients ID: {yclients_id})")


def check_service_options_details():
    """Детальная проверка ServiceOption"""
    print_section("ДЕТАЛИ ВАРИАНТОВ УСЛУГ (ServiceOption)")
    
    options = ServiceOption.objects.filter(is_active=True).select_related('service')
    
    for option in options:
        print(f"\n🔷 Option ID: {option.id}")
        print(f"   Услуга: {option.service.name}")
        print(f"   Длительность: {option.duration_min} мин")
        print(f"   Цена: {option.price}₽")
        print(f"   YClients ID: {option.yclients_service_id or 'НЕТ'}")
        
        # Получаем мастеров через service
        masters = option.service.masters.filter(is_active=True)
        print(f"   Мастеров для этой услуги: {masters.count()}")
        for master in masters:
            print(f"      ├─ {master.name}")


def test_filtering_logic():
    """Тестирование логики фильтрации"""
    print_section("ТЕСТ: ФИЛЬТРАЦИЯ МАСТЕРОВ ПО SERVICEOPTION")
    
    # Берём первый вариант услуги
    option = ServiceOption.objects.filter(
        is_active=True,
        yclients_service_id__isnull=False
    ).select_related('service').first()
    
    if not option:
        print("⚠️ Нет вариантов услуг с YClients ID")
        return
    
    print(f"\n📋 Тестовый вариант: {option.service.name} ({option.duration_min} мин)")
    print(f"   Option ID: {option.id}")
    print(f"   Service ID: {option.service.id}")
    print(f"   YClients Service ID: {option.yclients_service_id}")
    
    # Способ 1: Через Service (ПРАВИЛЬНЫЙ)
    print(f"\n✅ ПРАВИЛЬНЫЙ способ (через Service):")
    masters_correct = option.service.masters.filter(is_active=True)
    print(f"   Найдено мастеров: {masters_correct.count()}")
    for master in masters_correct:
        print(f"      ├─ {master.name} (ID: {master.id})")
    
    # Способ 2: Напрямую по YClients ID (НЕПРАВИЛЬНЫЙ - такой связи нет)
    print(f"\n❌ НЕПРАВИЛЬНЫЙ способ (прямая связь Master ↔ yclients_service_id):")
    print(f"   Такой связи НЕТ в Django моделях!")
    print(f"   Master связан с Service, НЕ с ServiceOption")
    
    print(f"\n💡 ВЫВОД:")
    print(f"   Для фильтрации мастеров по ServiceOption нужно:")
    print(f"   1. Получить ServiceOption по ID")
    print(f"   2. Получить связанный Service через option.service")
    print(f"   3. Получить мастеров через service.masters")


def test_api_filter_scenario():
    """Тест сценария API фильтрации"""
    print_section("СИМУЛЯЦИЯ API ЗАПРОСА")
    
    option = ServiceOption.objects.filter(
        is_active=True,
        yclients_service_id__isnull=False
    ).select_related('service').first()
    
    if not option:
        print("⚠️ Нет вариантов услуг")
        return
    
    print(f"\n🌐 GET /api/booking/get_staff/?service_option_id={option.id}")
    print(f"\n📥 Backend обрабатывает:")
    print(f"   1. Получает ServiceOption ID: {option.id}")
    print(f"   2. Загружает ServiceOption из БД")
    print(f"   3. Получает связанный Service: {option.service.name} (ID: {option.service.id})")
    print(f"   4. Получает YClients Service ID: {option.yclients_service_id}")
    
    print(f"\n🔍 ДВА ВАРИАНТА ФИЛЬТРАЦИИ:")
    
    # Вариант А: Django фильтрация
    print(f"\n   ВАРИАНТ А: Фильтрация в Django (быстро, может быть неточно)")
    masters_django = option.service.masters.filter(is_active=True)
    print(f"   ├─ Запрос: option.service.masters.filter(is_active=True)")
    print(f"   ├─ Результат: {masters_django.count()} мастеров")
    for master in masters_django:
        print(f"   │  ├─ {master.name}")
    print(f"   └─ Плюсы: Быстро, не нужен API запрос")
    print(f"      Минусы: Django БД может быть неактуальна")
    
    # Вариант Б: YClients API фильтрация
    print(f"\n   ВАРИАНТ Б: Фильтрация через YClients API (точно)")
    print(f"   ├─ API запрос: /book_staff/{'{company_id}'}?service_id={option.yclients_service_id}")
    print(f"   ├─ YClients вернёт: Актуальный список мастеров")
    print(f"   └─ Плюсы: Точные данные в реальном времени")
    print(f"      Минусы: Дополнительный API запрос")


def main():
    """Главная функция"""
    print("\n" + "🔍 ПРОВЕРКА СВЯЗЕЙ MASTER ↔ SERVICE ↔ SERVICEOPTION " + "\n")
    
    # Проверка структуры
    if not check_database_structure():
        print("\n❌ База данных пустая! Добавьте данные.")
        return
    
    # Проверка связей
    check_masters_services()
    check_services_masters()
    check_service_options_details()
    
    # Тесты логики
    test_filtering_logic()
    test_api_filter_scenario()
    
    print_section("ИТОГИ")
    print("""
✅ ПРАВИЛЬНЫЙ подход к фильтрации:
   
   1. API получает service_option_id
   2. Загружает ServiceOption из БД
   3. Получает option.service (связь через FK)
   4. Либо:
      А) Фильтрует в Django: option.service.masters.filter(is_active=True)
      Б) Запрашивает YClients API с option.yclients_service_id
   
❌ НЕПРАВИЛЬНЫЙ подход:
   
   Искать прямую связь Master ↔ yclients_service_id (её нет!)
   
💡 РЕКОМЕНДАЦИЯ:
   
   Использовать ВАРИАНТ Б (YClients API) для production,
   т.к. YClients знает точно кто из мастеров доступен прямо сейчас.
    """)


if __name__ == '__main__':
    main()