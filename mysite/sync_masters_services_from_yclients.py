#!/usr/bin/env python
"""
Скрипт синхронизации мастеров и их услуг из YClients в Django БД

Что делает:
1. Получает список всех мастеров из YClients API
2. Для каждого мастера получает список его услуг
3. Синхронизирует данные в Django БД (Master ↔ Service)

Запуск:
    python sync_masters_services_from_yclients.py
"""

import os
import sys
import django
from typing import List, Dict, Set

# Настройка Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mysite'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings.dev')
django.setup()

from services_app.models import Master, Service, ServiceOption
from services_app.yclients_api import get_yclients_api
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)


def print_section(title: str, emoji: str = "📋"):
    """Красивый заголовок секции"""
    print("\n" + "="*70)
    print(f"{emoji} {title}")
    print("="*70)


def get_all_staff_from_yclients() -> List[Dict]:
    """
    Получить список всех сотрудников из YClients
    
    Returns:
        List[Dict]: Список сотрудников с информацией
    """
    api = get_yclients_api()
    
    logger.info("🔍 Запрашиваем список сотрудников из YClients...")
    staff_list = api.get_staff()
    
    logger.info(f"✅ Получено сотрудников: {len(staff_list)}")
    return staff_list


def get_staff_services(staff_id: int) -> List[Dict]:
    """
    Получить список услуг которые оказывает сотрудник
    
    Args:
        staff_id: ID сотрудника в YClients
        
    Returns:
        List[Dict]: Список услуг сотрудника
    """
    api = get_yclients_api()
    
    try:
        # YClients API v2: GET /api/v1/company/{company_id}/services?staff_id={staff_id}
        endpoint = f'/api/v1/company/{api.company_id}/services'
        params = {'staff_id': staff_id}
        
        logger.info(f"   🔍 Запрос услуг для staff_id={staff_id}")
        
        # Важно! Нужен заголовок Accept
        headers = {
            'Accept': 'application/vnd.yclients.v2+json'
        }
        
        response = api._request('GET', endpoint, params=params, headers=headers)
        
        # Ответ в формате: {"success": true, "data": [...], "meta": {...}}
        if response.get('success'):
            services = response.get('data', [])
            logger.info(f"   ✅ Получено услуг: {len(services)}")
            return services
        else:
            logger.warning(f"   ⚠️ API вернул success=false")
            return []
        
    except Exception as e:
        logger.error(f"   ❌ Ошибка получения услуг для staff {staff_id}: {e}")
        return []


def sync_master_to_db(staff_data: Dict) -> Master:
    """
    Синхронизировать мастера в Django БД
    
    Args:
        staff_data: Данные мастера из YClients
        
    Returns:
        Master: Объект мастера Django
    """
    staff_id = staff_data.get('id')
    name = staff_data.get('name', 'Без имени')
    specialization = staff_data.get('specialization', '')
    avatar = staff_data.get('avatar')
    
    # Создаём или обновляем мастера
    master, created = Master.objects.update_or_create(
        id=staff_id,
        defaults={
            'name': name,
            'specialization': specialization,
            'is_active': True,
            # Можно добавить фото если нужно:
            # 'photo': avatar if avatar else None
        }
    )
    
    action = "создан" if created else "обновлён"
    logger.info(f"   {'➕' if created else '🔄'} Мастер {action}: {name} (ID: {staff_id})")
    
    return master


def find_service_by_yclients_id(yclients_service_id: str) -> Service:
    """
    Найти Service в Django по yclients_service_id
    
    Ищет через ServiceOption.yclients_service_id → Service
    
    Args:
        yclients_service_id: ID услуги в YClients
        
    Returns:
        Service или None
    """
    try:
        # Ищем ServiceOption с этим YClients ID
        option = ServiceOption.objects.filter(
            yclients_service_id=str(yclients_service_id),
            is_active=True
        ).select_related('service').first()
        
        if option:
            return option.service
        else:
            logger.warning(f"      ⚠️ Услуга YClients ID {yclients_service_id} не найдена в БД")
            return None
            
    except Exception as e:
        logger.error(f"      ❌ Ошибка поиска услуги {yclients_service_id}: {e}")
        return None


def sync_master_services(master: Master, yclients_services: List[Dict]) -> int:
    """
    Синхронизировать услуги мастера
    
    Args:
        master: Объект мастера Django
        yclients_services: Список услуг из YClients API v2
        
    Returns:
        int: Количество добавленных связей
    """
    if not yclients_services:
        logger.info(f"      ℹ️ У мастера нет услуг в YClients")
        return 0
    
    # Собираем Service объекты
    services_to_add: Set[Service] = set()
    not_found_count = 0
    
    for service_data in yclients_services:
        yclients_id = str(service_data.get('id'))
        service_title = service_data.get('title', 'Без названия')
        
        # Ищем Service в Django по yclients_service_id
        service = find_service_by_yclients_id(yclients_id)
        
        if service:
            services_to_add.add(service)
            logger.info(f"      ✅ {service.name} (YClients ID: {yclients_id})")
        else:
            not_found_count += 1
            if not_found_count <= 3:  # Показываем только первые 3
                logger.warning(f"      ⚠️ Не найдена: {service_title} (YClients ID: {yclients_id})")
    
    if not_found_count > 3:
        logger.warning(f"      ⚠️ ... и ещё {not_found_count - 3} не найдено")
    
    # Обновляем связи мастера
    if services_to_add:
        # Получаем текущие услуги мастера
        current_services = set(master.services.all())
        
        # Добавляем новые услуги (не удаляем старые!)
        new_services = services_to_add - current_services
        
        if new_services:
            master.services.add(*new_services)
            logger.info(f"      ➕ Добавлено новых услуг: {len(new_services)}")
            return len(new_services)
        else:
            logger.info(f"      ℹ️ Все услуги уже добавлены ({len(services_to_add)} шт)")
            return 0
    else:
        if yclients_services:
            logger.warning(f"      ⚠️ Ни одна из {len(yclients_services)} услуг не найдена в Django БД")
        return 0


def sync_all_masters_services():
    """
    Главная функция синхронизации
    
    ЛОГИКА:
    1. Получаем всех мастеров из YClients → создаём в Django
    2. Для каждого мастера получаем его услуги через API v2
    3. Ищем соответствующие Service в Django
    4. Добавляем связи Master ↔ Service
    """
    print_section("СИНХРОНИЗАЦИЯ МАСТЕРОВ И УСЛУГ ИЗ YCLIENTS", "🔄")
    
    # ШАГ 1: Получаем всех сотрудников
    staff_list = get_all_staff_from_yclients()
    
    if not staff_list:
        logger.error("❌ Не удалось получить список сотрудников")
        return
    
    total_masters_synced = 0
    total_services_added = 0
    
    # ШАГ 2: Обрабатываем каждого сотрудника
    for idx, staff_data in enumerate(staff_list, 1):
        staff_id = staff_data.get('id')
        staff_name = staff_data.get('name', 'Без имени')
        
        print_section(f"МАСТЕР {idx}/{len(staff_list)}: {staff_name}", "👤")
        
        # 2.1: Синхронизируем мастера в БД
        master = sync_master_to_db(staff_data)
        total_masters_synced += 1
        
        # 2.2: Получаем услуги сотрудника через API v2
        logger.info(f"\n   📋 Получаем услуги мастера...")
        yclients_services = get_staff_services(staff_id)
        
        # 2.3: Синхронизируем услуги
        logger.info(f"\n   🔗 Синхронизация услуг в Django БД...")
        added = sync_master_services(master, yclients_services)
        total_services_added += added
    
    # ИТОГИ
    print_section("ИТОГИ СИНХРОНИЗАЦИИ", "✅")
    print(f"""
    Обработано мастеров: {total_masters_synced}
    Добавлено связей (Мастер ↔ Услуга): {total_services_added}
    
    ✅ Синхронизация завершена успешно!
    """)


def show_statistics():
    """
    Показать статистику после синхронизации
    """
    print_section("СТАТИСТИКА В БД", "📊")
    
    # Мастера
    total_masters = Master.objects.filter(is_active=True).count()
    print(f"\n👥 Активных мастеров: {total_masters}")
    
    # Мастера с услугами
    masters_with_services = Master.objects.filter(
        is_active=True,
        services__isnull=False
    ).distinct().count()
    
    print(f"✅ Мастеров с услугами: {masters_with_services}")
    print(f"⚠️ Мастеров БЕЗ услуг: {total_masters - masters_with_services}")
    
    # Детали по каждому мастеру
    print("\n" + "-"*70)
    print("ДЕТАЛИ ПО МАСТЕРАМ:")
    print("-"*70)
    
    for master in Master.objects.filter(is_active=True).prefetch_related('services'):
        services_count = master.services.count()
        icon = "✅" if services_count > 0 else "⚠️"
        print(f"{icon} {master.name}: {services_count} услуг")
        
        if services_count > 0:
            for service in master.services.all()[:5]:  # Показываем первые 5
                print(f"   ├─ {service.name}")
            if services_count > 5:
                print(f"   └─ ... и ещё {services_count - 5}")


def main():
    """
    Главная функция
    """
    print("\n" + "🚀 СКРИПТ СИНХРОНИЗАЦИИ YCLIENTS → DJANGO" + "\n")
    
    try:
        # Синхронизация
        sync_all_masters_services()
        
        # Статистика
        show_statistics()
        
        print("\n" + "="*70)
        print("✅ ВСЁ ГОТОВО!")
        print("="*70)
        print("""
Что дальше:
1. Проверь данные в Django Admin
2. Запусти тесты: pytest test_master_service_matching.py
3. Проверь фильтрацию мастеров на сайте
        """)
        
    except Exception as e:
        logger.error(f"\n❌ ОШИБКА: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()