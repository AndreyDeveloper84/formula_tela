# test_book_dates.py
import requests
import json
from datetime import datetime, timedelta

COMPANY_ID = 884045
STAFF_ID = 4416525  # Инна Сазанова

PARTNER_TOKEN = "gmn9rncz9nhr66yj23yc"
USER_TOKEN = "7fcdd6c3643da0f14a4cdddbce34c9de"

date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

print(f"🔍 Проверяем доступные даты для мастера {STAFF_ID}")
print(f"   Компания: {COMPANY_ID}")
print(f"   Дата: {date}")
print("=" * 60)

url = f"https://api.yclients.com/api/v1/book_dates/{COMPANY_ID}"

headers = {
    "Authorization": f"Bearer {PARTNER_TOKEN}, User {USER_TOKEN}",
    "Accept": "application/vnd.yclients.v2+json",
    "Content-Type": "application/json"
}

params = {
    "staff_id": STAFF_ID,
}

print(f"\n📡 Запрос: {url}")
print(f"   Параметры: {params}")

response = requests.get(url, headers=headers, params=params)

print(f"\n📊 Статус: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print("\n✅ Ответ получен:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    
    if data.get('success') and data.get('data'):
        # Правильный доступ к данным
        booking_dates = data['data'].get('booking_dates', [])
        working_dates = data['data'].get('working_dates', [])
        
        print(f"\n📅 Доступных дат для записи: {len(booking_dates)}")
        print("\nБлижайшие 5 дат:")
        for date in booking_dates[:5]:
            print(f"  ✅ {date}")
        
        print(f"\n🕒 Рабочих дней: {len(working_dates)}")
else:
    print(f"\n❌ Ошибка: {response.status_code}")
    print(response.text)