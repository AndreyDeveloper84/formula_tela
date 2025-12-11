# test_available_times.py
import requests
import json

# Параметры
STAFF_ID = 4416525  # Инна Сазанова
DATE = "2025-12-15"  # Дата из доступных
SERVICE_ID = None  # Пока без услуги

url = f"http://localhost:8080/api/booking/available_times/"
params = {
    'staff_id': STAFF_ID,
    'date': DATE
}

if SERVICE_ID:
    params['service_id'] = SERVICE_ID

print(f"🔍 Тест: Получение свободного времени")
print(f"   Мастер: {STAFF_ID}")
print(f"   Дата: {DATE}")
print("=" * 60)

response = requests.get(url, params=params)

print(f"\nStatus: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    print("\n✅ Ответ:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    
    if data.get('success'):
        times = data['data']['times']
        print(f"\n🕒 Свободных слотов: {len(times)}")
        
        if times:
            print("\nПервые 10 слотов:")
            for time in times[:10]:
                print(f"  ⏰ {time}")
        else:
            print("\n⚠️ Нет свободных слотов на эту дату")
else:
    print(f"\n❌ Ошибка: {response.text}")