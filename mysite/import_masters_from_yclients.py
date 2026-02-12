#!/usr/bin/env python
"""
Импорт мастеров из YClients в Django

Что делает:
1. Получает всех сотрудников из YClients API
2. Синхронизирует их с Django БД (создаёт/обновляет)
3. Показывает детальную статистику

Запуск:
    python import_masters_from_yclients.py
    python import_masters_from_yclients.py --dry-run  # Без изменений в БД
"""

import os
import sys
import django
from typing import Dict, List, Tuple

# Настройка Django
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'mysite'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings.dev')
django.setup()

from services_app.yclients_api import get_yclients_api, YClientsAPIError
from services_app.models import Master
from django.db import transaction


def print_section(title: str, emoji: str = "📋", width: int = 70):
    """Красивый заголовок"""
    print("\n" + "="*width)
    print(f"{emoji} {title}")
    print("="*width)


def get_masters_from_yclients() -> List[Dict]:
    """
    Получить список мастеров из YClients API
    
    Returns:
        List[Dict]: Список мастеров из YClients
    """
    print_section("ШАГ 1: Получение мастеров из YClients API", "📥")
    
    try:
        api = get_yclients_api()
        
        print("🔌 Подключение к YClients API...")
        
        # Получаем всех сотрудников
        staff_list = api.get_staff()
        
        if not staff_list:
            print("❌ Не удалось получить мастеров из API")
            return []
        
        print(f"✅ Успешно получено сотрудников: {len(staff_list)}")
        
        # Показываем детали
        print("\n📋 Список мастеров из YClients:")
        print("-" * 70)
        
        for idx, staff in enumerate(staff_list, 1):
            staff_id = staff.get('id')
            name = staff.get('name', 'Без имени')
            specialization = staff.get('specialization', '')
            
            print(f"{idx}. {name}")
            print(f"   ID: {staff_id}")
            if specialization:
                print(f"   Специализация: {specialization}")
            
            # Показываем все доступные поля
            print(f"   Доступные поля: {', '.join(staff.keys())}")
            print()
        
        return staff_list
        
    except YClientsAPIError as e:
        print(f"❌ Ошибка YClients API: {e}")
        return []
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        return []


def map_yclients_to_django(yclients_staff: Dict) -> Dict:
    """
    Преобразовать данные YClients в формат Django
    
    Args:
        yclients_staff: Данные сотрудника из YClients
    
    Returns:
        Dict: Данные для Django модели Master
    """
    # Базовые поля (обязательные)
    django_data = {
        'id': yclients_staff.get('id'),
        'name': yclients_staff.get('name', 'Без имени'),
        'is_active': True  # По умолчанию активен
    }
    
    # Дополнительные поля (если есть в YClients)
    optional_fields = {
        'specialization': yclients_staff.get('specialization'),
        'bio': yclients_staff.get('information') or yclients_staff.get('comments'),
        'phone': yclients_staff.get('phone'),
        'email': yclients_staff.get('email'),
        'rating': yclients_staff.get('rating'),
    }
    
    # Добавляем только непустые поля
    for key, value in optional_fields.items():
        if value:
            django_data[key] = value
    
    return django_data


def sync_master_to_django(staff_data: Dict, dry_run: bool = False) -> Tuple[str, Master]:
    """
    Синхронизировать мастера в Django БД
    
    Args:
        staff_data: Данные из YClients
        dry_run: Если True, не сохраняет изменения
    
    Returns:
        Tuple[str, Master]: ('created'|'updated'|'unchanged', master_instance)
    """
    staff_id = staff_data.get('id')
    staff_name = staff_data.get('name', 'Без имени')
    
    # Преобразуем данные для Django
    django_data = map_yclients_to_django(staff_data)
    
    # Проверяем существует ли мастер
    try:
        master = Master.objects.get(id=staff_id)
        
        # Проверяем изменились ли данные
        changed = False
        changes = []
        
        for field, new_value in django_data.items():
            if field == 'id':
                continue
            
            old_value = getattr(master, field)
            
            if old_value != new_value:
                changed = True
                changes.append(f"{field}: '{old_value}' → '{new_value}'")
                
                if not dry_run:
                    setattr(master, field, new_value)
        
        if changed:
            if not dry_run:
                master.save()
            return 'updated', master, changes
        else:
            return 'unchanged', master, []
            
    except Master.DoesNotExist:
        # Создаём нового мастера
        if dry_run:
            # В dry-run режиме не сохраняем
            master = Master(**django_data)
            return 'created', master, []
        else:
            master = Master.objects.create(**django_data)
            return 'created', master, []


def import_masters(dry_run: bool = False) -> Dict:
    """
    Основная функция импорта мастеров
    
    Args:
        dry_run: Если True, не вносит изменения в БД
    
    Returns:
        Dict: Статистика импорта
    """
    print_section(
        "ИМПОРТ МАСТЕРОВ ИЗ YCLIENTS В DJANGO",
        "🔄"
    )
    
    if dry_run:
        print("⚠️ РЕЖИМ DRY-RUN: изменения НЕ будут сохранены в БД\n")
    
    # Шаг 1: Получаем мастеров из YClients
    yclients_masters = get_masters_from_yclients()
    
    if not yclients_masters:
        print("\n❌ Не удалось получить мастеров из YClients")
        return {
            'total': 0,
            'created': 0,
            'updated': 0,
            'unchanged': 0,
            'errors': 0
        }
    
    # Шаг 2: Синхронизируем с Django
    print_section("ШАГ 2: Синхронизация с Django БД", "🔄")
    
    stats = {
        'total': len(yclients_masters),
        'created': 0,
        'updated': 0,
        'unchanged': 0,
        'errors': 0
    }
    
    created_list = []
    updated_list = []
    unchanged_list = []
    errors_list = []
    
    # Обрабатываем каждого мастера
    for idx, staff_data in enumerate(yclients_masters, 1):
        staff_id = staff_data.get('id')
        staff_name = staff_data.get('name', 'Без имени')
        
        print(f"\n{idx}/{len(yclients_masters)} | {staff_name} (ID: {staff_id})")
        
        try:
            status, master, changes = sync_master_to_django(staff_data, dry_run)
            
            if status == 'created':
                stats['created'] += 1
                created_list.append(master)
                print(f"   ➕ СОЗДАН: {master.name}")
                
            elif status == 'updated':
                stats['updated'] += 1
                updated_list.append((master, changes))
                print(f"   ✏️ ОБНОВЛЁН: {master.name}")
                for change in changes:
                    print(f"      • {change}")
                    
            elif status == 'unchanged':
                stats['unchanged'] += 1
                unchanged_list.append(master)
                print(f"   ℹ️ БЕЗ ИЗМЕНЕНИЙ: {master.name}")
        
        except Exception as e:
            stats['errors'] += 1
            errors_list.append((staff_name, str(e)))
            print(f"   ❌ ОШИБКА: {e}")
    
    # Шаг 3: Итоговая статистика
    print_section("ШАГ 3: Итоги импорта", "📊")
    
    print(f"""
    📊 Статистика:
    
       Всего мастеров в YClients:  {stats['total']}
       
       ➕ Создано новых:            {stats['created']}
       ✏️ Обновлено:                {stats['updated']}
       ℹ️ Без изменений:            {stats['unchanged']}
       ❌ Ошибок:                   {stats['errors']}
    """)
    
    # Детали по созданным
    if created_list:
        print("\n➕ СОЗДАННЫЕ МАСТЕРА:")
        for master in created_list:
            print(f"   • {master.name} (ID: {master.id})")
    
    # Детали по обновлённым
    if updated_list:
        print("\n✏️ ОБНОВЛЁННЫЕ МАСТЕРА:")
        for master, changes in updated_list:
            print(f"   • {master.name} (ID: {master.id})")
            for change in changes[:3]:  # Показываем первые 3 изменения
                print(f"     - {change}")
    
    # Детали по ошибкам
    if errors_list:
        print("\n❌ ОШИБКИ:")
        for name, error in errors_list:
            print(f"   • {name}: {error}")
    
    # Шаг 4: Проверка БД
    print_section("ШАГ 4: Проверка Django БД", "✅")
    
    db_masters = Master.objects.filter(is_active=True)
    print(f"👥 Активных мастеров в БД: {db_masters.count()}")
    
    if db_masters.exists():
        print("\n📋 Список мастеров:")
        for idx, master in enumerate(db_masters, 1):
            print(f"   {idx}. {master.name} (ID: {master.id})")
    
    # Предупреждения
    if dry_run:
        print_section("⚠️ DRY-RUN MODE", "⚠️")
        print("""
    Это был пробный запуск!
    Изменения НЕ сохранены в БД.
    
    Для реального импорта запусти:
        python import_masters_from_yclients.py
        """)
    else:
        print_section("✅ ИМПОРТ ЗАВЕРШЁН", "✅")
        print(f"""
    ✅ Импорт успешно завершён!
    
    Что дальше:
    1. Проверь мастеров в Django Admin: /admin/services_app/master/
    2. Запусти импорт услуг мастеров:
       python diagnose_and_sync.py
    3. Протестируй связи:
       python test_master_service_links.py
        """)
    
    return stats


def show_comparison():
    """
    Сравнить мастеров YClients vs Django
    """
    print_section("СРАВНЕНИЕ YCLIENTS vs DJANGO", "🔍")
    
    # Получаем из YClients
    print("📥 Получаем мастеров из YClients...")
    yclients_masters = get_masters_from_yclients()
    
    if not yclients_masters:
        print("❌ Не удалось получить данные из YClients")
        return
    
    yclients_ids = {m['id']: m['name'] for m in yclients_masters}
    
    # Получаем из Django
    print("💾 Получаем мастеров из Django БД...")
    django_masters = Master.objects.all()
    django_ids = {m.id: m.name for m in django_masters}
    
    print(f"\n📊 Статистика:")
    print(f"   YClients: {len(yclients_ids)} мастеров")
    print(f"   Django:   {len(django_ids)} мастеров")
    
    # Сравнение
    in_yclients_only = set(yclients_ids.keys()) - set(django_ids.keys())
    in_django_only = set(django_ids.keys()) - set(yclients_ids.keys())
    in_both = set(yclients_ids.keys()) & set(django_ids.keys())
    
    print(f"\n🔍 Анализ:")
    print(f"   В обоих системах:          {len(in_both)}")
    print(f"   Только в YClients:         {len(in_yclients_only)}")
    print(f"   Только в Django:           {len(in_django_only)}")
    
    if in_yclients_only:
        print(f"\n⚠️ Мастера ТОЛЬКО в YClients (нужно импортировать):")
        for master_id in in_yclients_only:
            print(f"   • {yclients_ids[master_id]} (ID: {master_id})")
    
    if in_django_only:
        print(f"\n⚠️ Мастера ТОЛЬКО в Django (нет в YClients):")
        for master_id in in_django_only:
            print(f"   • {django_ids[master_id]} (ID: {master_id})")
    
    if not in_yclients_only and not in_django_only:
        print(f"\n✅ Все мастера синхронизированы!")


def main():
    """Главная функция"""
    import sys
    
    # Парсим аргументы
    dry_run = '--dry-run' in sys.argv
    compare = '--compare' in sys.argv
    
    if compare:
        show_comparison()
    else:
        import_masters(dry_run=dry_run)
    
    print("\n" + "="*70 + "\n")


if __name__ == '__main__':
    main()