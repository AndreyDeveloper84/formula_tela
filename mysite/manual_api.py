# test_api.py
import requests
import json

def test_staff_endpoint(show_all=False):
    """Тест get_staff endpoint"""
    url = 'http://localhost:8080/api/booking/get_staff/'
    if show_all:
        url += '?show_all=1'
    
    print(f"\n🔍 Тест: {url}")
    print("=" * 60)
    
    response = requests.get(url)
    
    print(f"Status Code: {response.status_code}")
    
    if response.status_code != 200:
        print(f"❌ Ошибка: {response.text}")
        return
    
    data = response.json()
    
    if not data.get('success'):
        print(f"❌ API вернул ошибку: {data.get('error', 'Unknown')}")
        return
    
    # Красиво выводим
    print("\n📊 Статистика:")
    meta = data.get('meta', {})
    print(f"  Всего мастеров: {meta.get('total', 0)}")
    print(f"  Активных: {meta.get('active', 0)}")
    print(f"  Доступны для записи (bookable): {meta.get('bookable', 0)}")
    print(f"  Скрыто: {meta.get('hidden', 0)}")
    print(f"  Уволено: {meta.get('fired', 0)}")
    print(f"  Удалено: {meta.get('deleted', 0)}")
    
    print(f"\n👥 Мастера (показано {data.get('count', 0)}):")
    for staff in data.get('data', []):
        # Эмодзи статуса
        if staff['bookable']:
            status_emoji = "✅"
        elif staff.get('deleted'):
            status_emoji = "🗑️"
        elif staff.get('fired'):
            status_emoji = "🚫"
        elif staff.get('hidden'):
            status_emoji = "👻"
        else:
            status_emoji = "⚠️"
        
        print(f"\n  {status_emoji} {staff['name']}")
        print(f"     ID: {staff['id']}")
        print(f"     Специализация: {staff['specialization']}")
        print(f"     Рейтинг: {staff['rating']} ({staff['votes_count']} голосов)")
        print(f"     Статус: {staff['availability_info']}")
        print(f"     Флаги: bookable={staff['bookable']}, hidden={staff.get('hidden')}, fired={staff.get('fired')}")
    
    print("\n" + "=" * 60)
    
    # Полный JSON (если нужно)
    if input("\nПоказать полный JSON? (y/n): ").lower() == 'y':
        print("\n" + json.dumps(data, indent=2, ensure_ascii=False))

# Запускаем тесты
if __name__ == '__main__':
    print("🧪 ТЕСТ 1: Только активные мастера (по умолчанию)")
    test_staff_endpoint(show_all=False)
    
    print("\n" + "=" * 80 + "\n")
    
    print("🧪 ТЕСТ 2: Все мастера (включая уволенных/скрытых)")
    test_staff_endpoint(show_all=True)