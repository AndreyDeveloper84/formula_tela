# test_available_dates.py

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'mysite.settings')
django.setup()

from services_app.yclients_api import get_yclients_api

def test_available_dates():
    api = get_yclients_api()
    
    # Тестируем для Инны Сазановой (ID: 4416525)
    staff_id = 4416525
    
    print(f"\n🔍 Запрос доступных дат для мастера {staff_id}...")
    
    try:
        dates = api.get_book_dates(staff_id=staff_id)
        
        print(f"\n✅ Результат:")
        print(f"   Найдено дат: {len(dates)}")
        
        if dates:
            print(f"\n📅 Доступные даты:")
            for date in dates[:10]:  # Показываем первые 10
                print(f"   - {date}")
        else:
            print("\n⚠️ Даты не найдены!")
            print("\n🔍 Проверяем что возвращает API...")
            
            # Прямой запрос к API
            response = api._request(
                'GET',
                f'/book_dates/{api.company_id}',
                params={'staff_id': staff_id}
            )
            
            print(f"\n📦 Сырой ответ от YClients API:")
            print(f"   Type: {type(response)}")
            print(f"   Content: {response}")
            
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    test_available_dates()