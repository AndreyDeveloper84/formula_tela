# test_create_booking.py
import requests
import json

url = "http://localhost:8080/api/booking/create/"

# Используем реальный ID услуги из YClients
data = {
    "staff_id": 4416525,  # Инна Сазанова
    "service_ids": [22396770],  # Массаж лица (30 мин, 1500₽)
    "date": "2025-12-15",
    "time": "14:00",
    "client": {
        "name": "Тестовый Клиент API",
        "phone": "79001234567",
        "email": "test@formulatela.ru"
    },
    "comment": "Тестовая запись через Django API"
}

print("🔖 Тест: Создание записи")
print(f"   Мастер: {data['staff_id']}")
print(f"   Услуги: {data['service_ids']}")
print(f"   Дата/время: {data['date']} {data['time']}")
print(f"   Клиент: {data['client']['name']}")
print("=" * 60)

response = requests.post(url, json=data)

print(f"\nStatus: {response.status_code}")
print(f"\nОтвет:")
print(json.dumps(response.json(), indent=2, ensure_ascii=False))

if response.status_code == 200 and response.json().get('success'):
    booking = response.json()['data']
    print("\n" + "=" * 60)
    print("✅ ЗАПИСЬ СОЗДАНА УСПЕШНО!")
    print(f"   Booking ID: {booking.get('booking_id')}")
    print(f"   Hash: {booking.get('booking_hash')}")
    print(f"   Мастер: {booking.get('staff_name')}")
    print(f"   Дата/время: {booking.get('datetime')}")