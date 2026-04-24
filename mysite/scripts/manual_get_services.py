# test_get_services.py
import os
import sys
import requests
import json

PARTNER_TOKEN = os.getenv("YCLIENTS_PARTNER_TOKEN")
if not PARTNER_TOKEN:
    sys.exit("Set YCLIENTS_PARTNER_TOKEN in env (.env)")

# Получаем список услуг из YClients
url = "https://api.yclients.com/api/v1/book_services/884045"

headers = {
    "Authorization": f"Bearer {PARTNER_TOKEN}",
    "Accept": "application/vnd.yclients.v2+json",
    "Content-Type": "application/json"
}

params = {
    "staff_id": 4416525  # Инна Сазанова
}

print("🔍 Получение списка услуг для мастера 4416525")
print("=" * 60)

response = requests.get(url, headers=headers, params=params)

print(f"\nStatus: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    
    if data.get('success'):
        services = data['data'].get('services', [])
        
        print(f"\n✅ Найдено услуг: {len(services)}")
        print("\nПервые 10 услуг:")
        
        for svc in services[:10]:
            print(f"\n  ID: {svc['id']}")
            print(f"  Название: {svc['title']}")
            print(f"  Цена: {svc.get('price_min', 0)} - {svc.get('price_max', 0)} ₽")
            if 'seance_length' in svc:
                print(f"  Длительность: {svc['seance_length'] // 60} мин")
        
        print("\n📋 Скопируйте ID нужных услуг в test_create_booking.py")
    else:
        print(f"\n❌ API вернул success=false")
        print(json.dumps(data, indent=2, ensure_ascii=False))
else:
    print(f"\n❌ Ошибка: {response.text}")