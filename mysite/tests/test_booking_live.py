"""
Live-тесты бронирования с реальным YClients API.

Запуск (требует доступа к api.yclients.com):
    pytest mysite/tests/test_booking_live.py -v -s

В CI эти тесты ПРОПУСКАЮТСЯ автоматически (маркер `live` не включён в addopts).
Чтобы принудительно пропустить: pytest -m "not live"

Что тестируем:
    1. Диагностика БД: какие ServiceOption имеют yclients_service_id
    2. Прямые вызовы YClients API: get_staff, get_book_dates, get_available_times
    3. Django-вью через test client: /api/booking/get_staff/, available_dates, available_times
    4. Полный флоу: get_staff → available_dates → available_times
"""

import pytest
import requests as _requests

# ── Проверка доступности API ────────────────────────────────────────────────

def _yclients_reachable() -> bool:
    """True если api.yclients.com отвечает JSON (не HTML 403 WAF)."""
    try:
        r = _requests.get(
            "https://api.yclients.com/api/v1/company/884045",
            timeout=5,
        )
        return "json" in r.headers.get("Content-Type", "")
    except Exception:
        return False


YCLIENTS_SKIP = pytest.mark.skipif(
    not _yclients_reachable(),
    reason="api.yclients.com недоступен с текущего IP (WAF-блокировка). "
           "Попробуйте с другой сети или отключите VPN.",
)

pytestmark = pytest.mark.live


# ── 1. Диагностика БД ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_service_options_yclients_coverage():
    """
    Показывает сколько активных ServiceOption имеют yclients_service_id.
    НЕ падает — только диагностика.
    """
    from services_app.models import ServiceOption

    all_opts = ServiceOption.objects.filter(is_active=True)
    with_id = all_opts.exclude(yclients_service_id__isnull=True).exclude(yclients_service_id="")
    without_id_count = all_opts.count() - with_id.count()

    print(f"\n{'='*50}")
    print(f"ServiceOptions (активных): {all_opts.count()}")
    print(f"  [OK  ] с yclients_service_id:    {with_id.count()}")
    print(f"  [MISS] без yclients_service_id: {without_id_count}")

    if with_id.exists():
        print("\nСписок с yclients_service_id:")
        for opt in with_id[:20]:
            print(f"  id={opt.id:<4}  yclients_id={opt.yclients_service_id:<10}  {opt}")
    else:
        print("\n⚠ НИ У ОДНОГО варианта услуги не заполнен yclients_service_id!")
        print("  Это основная причина пустого ответа /api/booking/get_staff/")
        print("  Исправить: Admin → ServiceOption → поле «ID услуги в YCLIENTS»")

    # Не проваливаем тест — это диагностический вывод
    # Раскомментируйте строку ниже, чтобы сделать тест «строгим»:
    # assert with_id.count() > 0, "Нет ServiceOption с yclients_service_id — бронирование сломано"


# ── 2. Прямые вызовы YClients API ───────────────────────────────────────────

@pytest.mark.django_db
@YCLIENTS_SKIP
def test_yclients_get_all_staff():
    """Все мастера из YClients (без фильтра по услуге)."""
    from services_app.yclients_api import get_yclients_api

    api = get_yclients_api()
    staff = api.get_staff()

    print(f"\n{'='*50}")
    print(f"Мастера из YClients: {len(staff)}")
    for s in staff:
        print(f"  id={s.get('id'):<10}  {s.get('name', '—'):<20}  {s.get('specialization', '')}")

    assert isinstance(staff, list), "get_staff() должен вернуть список"
    assert len(staff) > 0, (
        "YClients вернул пустой список мастеров. "
        "Проверьте: права токена, company_id, наличие мастеров в кабинете YClients."
    )


@pytest.mark.django_db
@YCLIENTS_SKIP
def test_yclients_get_staff_by_service():
    """Мастера для конкретной услуги (берём первый yclients_service_id из БД)."""
    from services_app.models import ServiceOption
    from services_app.yclients_api import get_yclients_api

    opt = (
        ServiceOption.objects
        .filter(is_active=True)
        .exclude(yclients_service_id__isnull=True)
        .exclude(yclients_service_id="")
        .first()
    )
    if not opt:
        pytest.skip("Нет ServiceOption с yclients_service_id — заполните в Admin")

    service_id = int(opt.yclients_service_id)
    api = get_yclients_api()
    staff = api.get_staff(service_id=service_id)

    print(f"\n{'='*50}")
    print(f"Услуга: {opt}  (yclients_service_id={service_id})")
    print(f"Мастеров для этой услуги: {len(staff)}")
    for s in staff:
        print(f"  id={s.get('id'):<10}  {s.get('name', '—')}")

    assert isinstance(staff, list), "get_staff(service_id=N) должен вернуть список"


@pytest.mark.django_db
@YCLIENTS_SKIP
def test_yclients_get_book_dates():
    """Доступные даты для первого мастера."""
    from services_app.yclients_api import get_yclients_api

    api = get_yclients_api()
    staff = api.get_staff()
    if not staff:
        pytest.skip("Нет мастеров в YClients")

    staff_id = staff[0]["id"]
    staff_name = staff[0].get("name", "—")
    dates = api.get_book_dates(staff_id=staff_id)

    print(f"\n{'='*50}")
    print(f"Мастер: {staff_name} (id={staff_id})")
    print(f"Доступных дат: {len(dates)}")
    if dates:
        print("  " + "  ".join(dates[:10]))

    assert isinstance(dates, list), "get_book_dates() должен вернуть список"
    assert len(dates) > 0, (
        f"У мастера {staff_name} (id={staff_id}) нет доступных дат для записи"
    )


@pytest.mark.django_db
@YCLIENTS_SKIP
def test_yclients_get_available_times():
    """Свободные слоты для первого мастера на первую доступную дату."""
    from services_app.yclients_api import get_yclients_api

    api = get_yclients_api()
    staff = api.get_staff()
    if not staff:
        pytest.skip("Нет мастеров в YClients")

    staff_id = staff[0]["id"]
    staff_name = staff[0].get("name", "—")

    dates = api.get_book_dates(staff_id=staff_id)
    if not dates:
        pytest.skip(f"У мастера {staff_name} нет доступных дат")

    target_date = dates[0]
    times = api.get_available_times(staff_id=staff_id, date=target_date)

    print(f"\n{'='*50}")
    print(f"Мастер: {staff_name} (id={staff_id})")
    print(f"Дата: {target_date}")
    print(f"Свободных слотов: {len(times)}")
    if times:
        print("  " + "  ".join(times[:12]))

    assert isinstance(times, list), "get_available_times() должен вернуть список"
    assert len(times) > 0, (
        f"У мастера {staff_name} нет свободных слотов на {target_date}"
    )


# ── 3. Django-вью через test client ─────────────────────────────────────────

@pytest.mark.django_db
@YCLIENTS_SKIP
def test_django_api_get_staff(client):
    """GET /api/booking/get_staff/?service_option_id=N возвращает мастеров."""
    from services_app.models import ServiceOption

    opt = (
        ServiceOption.objects
        .filter(is_active=True)
        .exclude(yclients_service_id__isnull=True)
        .exclude(yclients_service_id="")
        .first()
    )
    if not opt:
        pytest.skip("Нет ServiceOption с yclients_service_id")

    resp = client.get(f"/api/booking/get_staff/?service_option_id={opt.id}")

    print(f"\n{'='*50}")
    print(f"GET /api/booking/get_staff/?service_option_id={opt.id}")
    print(f"Услуга: {opt}")
    print(f"HTTP {resp.status_code}")
    data = resp.json()
    print(f"success={data.get('success')}  count={data.get('count')}")
    if data.get("data"):
        for m in data["data"][:5]:
            print(f"  {m.get('name')}  id={m.get('id')}")

    assert resp.status_code == 200, f"Ожидали 200, получили {resp.status_code}"
    assert data["success"] is True, f"success=False: {data}"
    assert isinstance(data["data"], list), "data должен быть списком"


@pytest.mark.django_db
@YCLIENTS_SKIP
def test_django_api_available_dates(client):
    """GET /api/booking/available_dates/?staff_id=N возвращает даты."""
    from services_app.yclients_api import get_yclients_api

    # Получаем первого мастера прямым вызовом API
    api = get_yclients_api()
    staff = api.get_staff()
    if not staff:
        pytest.skip("Нет мастеров в YClients")

    staff_id = staff[0]["id"]
    resp = client.get(f"/api/booking/available_dates/?staff_id={staff_id}")

    print(f"\n{'='*50}")
    print(f"GET /api/booking/available_dates/?staff_id={staff_id}")
    print(f"HTTP {resp.status_code}")
    data = resp.json()
    print(f"success={data.get('success')}")
    dates = data.get("data", {}).get("dates", [])
    print(f"Дат: {len(dates)}  Первые: {dates[:5]}")

    assert resp.status_code == 200
    assert data["success"] is True
    assert isinstance(dates, list)


@pytest.mark.django_db
@YCLIENTS_SKIP
def test_django_api_available_times(client):
    """GET /api/booking/available_times/?staff_id=N&date=D возвращает слоты."""
    from services_app.yclients_api import get_yclients_api

    api = get_yclients_api()
    staff = api.get_staff()
    if not staff:
        pytest.skip("Нет мастеров в YClients")

    staff_id = staff[0]["id"]
    dates = api.get_book_dates(staff_id=staff_id)
    if not dates:
        pytest.skip("Нет доступных дат")

    resp = client.get(
        f"/api/booking/available_times/?staff_id={staff_id}&date={dates[0]}"
    )

    print(f"\n{'='*50}")
    print(f"GET /api/booking/available_times/?staff_id={staff_id}&date={dates[0]}")
    print(f"HTTP {resp.status_code}")
    data = resp.json()
    print(f"success={data.get('success')}")
    times = data.get("data", {}).get("times", [])
    print(f"Слотов: {len(times)}  Первые: {times[:8]}")

    assert resp.status_code == 200
    assert data["success"] is True
    assert isinstance(times, list)


# ── 4. Полный флоу бронирования ─────────────────────────────────────────────

@pytest.mark.django_db
@YCLIENTS_SKIP
def test_full_booking_flow(client):
    """
    Полный флоу: выбор мастера → даты → слота.
    Имитирует то, что делает виджет бронирования на сайте.
    """
    from services_app.models import ServiceOption
    from services_app.yclients_api import get_yclients_api

    print(f"\n{'='*50}")
    print("ПОЛНЫЙ ФЛО БРОНИРОВАНИЯ")
    print("=" * 50)

    # Шаг 1: выбираем услугу
    opt = (
        ServiceOption.objects
        .filter(is_active=True)
        .exclude(yclients_service_id__isnull=True)
        .exclude(yclients_service_id="")
        .first()
    )
    if not opt:
        pytest.skip("Нет ServiceOption с yclients_service_id")

    print(f"\n[1] Услуга: {opt} (yclients_service_id={opt.yclients_service_id})")

    # Шаг 2: получаем мастеров
    resp = client.get(f"/api/booking/get_staff/?service_option_id={opt.id}")
    assert resp.status_code == 200
    staff_data = resp.json()
    print(f"[2] Мастеров для услуги: {staff_data.get('count')}")
    assert staff_data["success"] is True

    masters = staff_data.get("data", [])
    if not masters:
        # Fallback: берём любого мастера
        api = get_yclients_api()
        masters = api.get_staff()
        if not masters:
            pytest.skip("YClients не вернул ни одного мастера")
        masters = [{"id": masters[0]["id"], "name": masters[0].get("name", "?")}]
        print(f"  (мастеров по услуге 0, используем первого из всех: {masters[0]['name']})")

    master = masters[0]
    print(f"  Мастер: {master.get('name')}  id={master.get('id')}")

    # Шаг 3: получаем даты
    resp = client.get(f"/api/booking/available_dates/?staff_id={master['id']}")
    assert resp.status_code == 200
    dates_data = resp.json()
    dates = dates_data.get("data", {}).get("dates", [])
    print(f"[3] Доступных дат: {len(dates)}  Первые: {dates[:5]}")
    assert dates_data["success"] is True

    if not dates:
        pytest.skip(f"У мастера {master.get('name')} нет доступных дат")

    # Шаг 4: получаем слоты
    resp = client.get(
        f"/api/booking/available_times/"
        f"?staff_id={master['id']}&date={dates[0]}&service_option_id={opt.id}"
    )
    assert resp.status_code == 200
    times_data = resp.json()
    times = times_data.get("data", {}).get("times", [])
    print(f"[4] Свободных слотов на {dates[0]}: {len(times)}  Первые: {times[:6]}")
    assert times_data["success"] is True

    print(f"\n{'='*50}")
    print("РЕЗУЛЬТАТ:")
    print(f"  Услуга:  {opt}")
    print(f"  Мастер:  {master.get('name')} (id={master.get('id')})")
    print(f"  Дата:    {dates[0]}")
    print(f"  Слоты:   {', '.join(times[:6])}" + (" ..." if len(times) > 6 else ""))
    print("=" * 50)
