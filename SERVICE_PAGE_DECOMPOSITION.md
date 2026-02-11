# Декомпозиция: Страница услуги + Онлайн-запись

## 1. Схема данных (Entity Relationship)

```
┌─────────────────────┐
│   ServiceCategory   │
├─────────────────────┤
│ id                  │
│ name                │
│ description         │
│ order               │
└─────────┬───────────┘
          │ 1:N
          ▼
┌─────────────────────┐
│      Service        │
├─────────────────────┤
│ id                  │
│ name                │
│ short               │
│ description         │
│ is_active           │
│ is_popular          │
│ category_id (FK)    │
│ image (?)           │  ← НЕТ В МОДЕЛИ!
│ duration (legacy)   │
│ price (legacy)      │
└─────────┬───────────┘
          │ 1:N
          ▼
┌─────────────────────┐
│   ServiceOption     │
├─────────────────────┤
│ id                  │
│ service_id (FK)     │
│ name                │
│ duration_min        │
│ unit_type           │  ← session/zone/visit
│ units               │  ← количество (1, 5, 10...)
│ price               │
│ is_active           │
│ order               │
│ yclients_service_id │  ← КЛЮЧЕВОЕ для бронирования!
└─────────────────────┘
```

---

## 2. Данные для страницы услуги

### 2.1 Информация об услуге (статическая)

| Поле | Источник | Обязательно | Примечание |
|------|----------|-------------|------------|
| `service.id` | Service | ✅ | PK |
| `service.name` | Service | ✅ | "VelaShape" |
| `service.short` | Service | ❌ | Краткое название |
| `service.description` | Service | ❌ | Полное описание |
| `service.category` | ServiceCategory | ❌ | FK на категорию |
| `service.category.name` | ServiceCategory | ❌ | "Массаж" |
| `service.is_active` | Service | ✅ | Должен быть True |
| `service.image` | Service | ❌ | ⚠️ ПОЛЯ НЕТ В МОДЕЛИ! |

### 2.2 Варианты услуги (для формы бронирования)

| Поле | Источник | Обязательно | Примечание |
|------|----------|-------------|------------|
| `option.id` | ServiceOption | ✅ | PK |
| `option.duration_min` | ServiceOption | ✅ | 30, 50, 60... |
| `option.units` | ServiceOption | ✅ | 1, 5, 10... |
| `option.unit_type` | ServiceOption | ✅ | session/zone/visit |
| `option.price` | ServiceOption | ✅ | 6000, 25000... |
| `option.is_active` | ServiceOption | ✅ | Должен быть True |
| `option.yclients_service_id` | ServiceOption | ✅⚠️ | **КРИТИЧНО для YClients!** |

### 2.3 Данные для бронирования (динамические, из YClients API)

| Данные | API Endpoint | Когда загружать |
|--------|--------------|-----------------|
| Список мастеров | `/api/booking/get_staff/` | После выбора варианта услуги |
| Доступные даты | `/api/booking/available_dates/` | После выбора мастера |
| Доступное время | `/api/booking/available_times/` | После выбора даты |

---

## 3. Структура View (что передаём в шаблон)

```python
# website/views.py

def service_detail(request, service_id):
    """
    Страница конкретной услуги с формой бронирования
    """
    
    # 1. Получаем услугу
    service = get_object_or_404(
        Service.objects.select_related('category'),
        pk=service_id,
        is_active=True
    )
    
    # 2. Получаем активные варианты услуги
    options = service.options.filter(is_active=True).order_by('order', 'duration_min', 'units')
    
    # 3. Проверяем наличие yclients_service_id
    options_with_yclients = options.exclude(yclients_service_id__isnull=True).exclude(yclients_service_id='')
    
    # 4. Вычисляем данные для формы
    durations = sorted(set(opt.duration_min for opt in options_with_yclients))
    
    # 5. Другие услуги категории (для блока "Другие услуги")
    other_services = Service.objects.filter(
        category=service.category,
        is_active=True
    ).exclude(pk=service.pk)[:4]
    
    context = {
        'service': service,
        'options': list(options_with_yclients),  # Только с yclients_id!
        'options_count': options_with_yclients.count(),
        'durations': durations,
        'durations_count': len(durations),
        'other_services': other_services,
        'settings': SiteSettings.objects.first(),
    }
    
    return render(request, 'website/service_detail.html', context)
```

---

## 4. План интеграции (последовательные этапы)

### Этап 1: Подготовка данных ✅
- [ ] **1.1** Проверить модель Service — добавить поле `image` если нужно
- [ ] **1.2** Убедиться что в БД есть услуги с `is_active=True`
- [ ] **1.3** Убедиться что есть ServiceOption с `yclients_service_id`
- [ ] **1.4** Создать view `service_detail` 
- [ ] **1.5** Добавить URL `/services/<int:service_id>/`

### Этап 2: Статичная часть страницы
- [ ] **2.1** Интегрировать баннер (название, описание)
- [ ] **2.2** Интегрировать изображение услуги
- [ ] **2.3** Интегрировать блок "Другие услуги"
- [ ] **2.4** Проверить базовый рендеринг страницы

### Этап 3: Форма бронирования (статика)
- [ ] **3.1** Интегрировать grid-сетку формы (CSS)
- [ ] **3.2** Отрендерить select длительности
- [ ] **3.3** Отрендерить select количества
- [ ] **3.4** Отрендерить select мастера (пустой)
- [ ] **3.5** Отрендерить input даты
- [ ] **3.6** Отрендерить select времени (пустой)
- [ ] **3.7** Отрендерить поле стоимости

### Этап 4: JavaScript логика
- [ ] **4.1** Передать данные опций в JS (`serviceOptions`)
- [ ] **4.2** Реализовать обновление цены при выборе
- [ ] **4.3** Реализовать загрузку мастеров (fetch)
- [ ] **4.4** Реализовать загрузку дат (Flatpickr)
- [ ] **4.5** Реализовать загрузку времени
- [ ] **4.6** Реализовать отправку формы

### Этап 5: Модальное окно подтверждения
- [ ] **5.1** Интегрировать модальное окно
- [ ] **5.2** Реализовать валидацию контактов
- [ ] **5.3** Реализовать создание записи в YClients
- [ ] **5.4** Обработка успеха/ошибки

---

## 5. Тесты успешного выполнения

### 5.1 Unit-тесты (pytest)

```python
# tests/test_service_detail.py

import pytest
from django.urls import reverse
from services_app.models import Service, ServiceOption, ServiceCategory

@pytest.fixture
def category():
    return ServiceCategory.objects.create(name="Массаж", order=1)

@pytest.fixture
def service(category):
    return Service.objects.create(
        name="VelaShape",
        category=category,
        is_active=True
    )

@pytest.fixture
def option(service):
    return ServiceOption.objects.create(
        service=service,
        duration_min=50,
        units=1,
        unit_type='session',
        price=6000,
        is_active=True,
        yclients_service_id='12345678'
    )


class TestServiceDetailView:
    """Тесты view страницы услуги"""
    
    @pytest.mark.django_db
    def test_service_detail_returns_200(self, client, service, option):
        """Страница услуги возвращает 200"""
        url = reverse('website:service_detail', args=[service.id])
        response = client.get(url)
        assert response.status_code == 200
    
    @pytest.mark.django_db
    def test_service_detail_contains_service_name(self, client, service, option):
        """Страница содержит название услуги"""
        url = reverse('website:service_detail', args=[service.id])
        response = client.get(url)
        assert service.name.encode() in response.content
    
    @pytest.mark.django_db
    def test_service_detail_context_has_options(self, client, service, option):
        """Контекст содержит варианты услуги"""
        url = reverse('website:service_detail', args=[service.id])
        response = client.get(url)
        assert 'options' in response.context
        assert len(response.context['options']) == 1
    
    @pytest.mark.django_db
    def test_inactive_service_returns_404(self, client, category):
        """Неактивная услуга возвращает 404"""
        inactive = Service.objects.create(
            name="Inactive",
            category=category,
            is_active=False
        )
        url = reverse('website:service_detail', args=[inactive.id])
        response = client.get(url)
        assert response.status_code == 404
    
    @pytest.mark.django_db
    def test_options_without_yclients_id_excluded(self, client, service):
        """Варианты без yclients_service_id не включаются"""
        # Вариант БЕЗ yclients_id
        ServiceOption.objects.create(
            service=service,
            duration_min=60,
            units=1,
            price=5000,
            is_active=True,
            yclients_service_id=None  # НЕТ ID!
        )
        # Вариант С yclients_id
        ServiceOption.objects.create(
            service=service,
            duration_min=50,
            units=1,
            price=6000,
            is_active=True,
            yclients_service_id='123456'
        )
        
        url = reverse('website:service_detail', args=[service.id])
        response = client.get(url)
        
        # Должен быть только 1 вариант (с yclients_id)
        assert response.context['options_count'] == 1


class TestServiceDetailTemplate:
    """Тесты шаблона страницы услуги"""
    
    @pytest.mark.django_db
    def test_booking_form_present(self, client, service, option):
        """На странице есть форма бронирования"""
        url = reverse('website:service_detail', args=[service.id])
        response = client.get(url)
        assert b'id="booking-form"' in response.content
    
    @pytest.mark.django_db
    def test_duration_select_present(self, client, service, option):
        """На странице есть select длительности"""
        url = reverse('website:service_detail', args=[service.id])
        response = client.get(url)
        assert b'id="duration-select"' in response.content
    
    @pytest.mark.django_db
    def test_master_select_present(self, client, service, option):
        """На странице есть select мастера"""
        url = reverse('website:service_detail', args=[service.id])
        response = client.get(url)
        assert b'id="master-select"' in response.content
    
    @pytest.mark.django_db
    def test_service_options_in_js(self, client, service, option):
        """Данные опций передаются в JavaScript"""
        url = reverse('website:service_detail', args=[service.id])
        response = client.get(url)
        assert b'serviceOptions' in response.content
        assert b'yclientsId' in response.content
```

### 5.2 Интеграционные тесты (E2E чеклист)

```markdown
## Чеклист ручного тестирования

### Загрузка страницы
- [ ] Страница открывается без ошибок 500
- [ ] Название услуги отображается
- [ ] Описание услуги отображается (если есть)
- [ ] Изображение отображается (или placeholder)

### Форма бронирования - визуал
- [ ] Форма имеет grid-сетку 3 колонки
- [ ] Select длительности видимый
- [ ] Select количества видимый
- [ ] Select мастера видимый (с placeholder)
- [ ] Input даты видимый
- [ ] Select времени видимый
- [ ] Поле стоимости видимое

### Форма бронирования - логика
- [ ] При выборе длительности обновляется список количества
- [ ] При выборе количества обновляется стоимость
- [ ] При выборе варианта загружаются мастера (AJAX)
- [ ] При выборе мастера открывается календарь
- [ ] В календаре доступны только разрешённые даты
- [ ] При выборе даты загружается время (AJAX)
- [ ] Время разбито на группы (утро/день/вечер)

### Отправка формы
- [ ] При нажатии "Записаться" открывается модальное окно
- [ ] В модальном окне отображается сводка записи
- [ ] Валидация имени работает
- [ ] Валидация телефона работает
- [ ] При успешной отправке показывается сообщение
- [ ] Запись создаётся в YClients (проверить в админке YClients)

### Адаптивность
- [ ] На мобильном форма в 1 колонку
- [ ] Календарь адаптивный
- [ ] Модальное окно адаптивное
```

### 5.3 API тесты

```python
# tests/test_booking_api.py

import pytest
from django.urls import reverse

class TestBookingAPI:
    """Тесты API бронирования"""
    
    @pytest.mark.django_db
    def test_get_staff_returns_json(self, client):
        """Endpoint мастеров возвращает JSON"""
        url = '/api/booking/get_staff/'
        response = client.get(url)
        assert response.status_code == 200
        assert response['Content-Type'] == 'application/json'
    
    @pytest.mark.django_db
    def test_get_staff_with_service_option(self, client, option):
        """Фильтрация мастеров по варианту услуги"""
        url = f'/api/booking/get_staff/?service_option_id={option.id}'
        response = client.get(url)
        data = response.json()
        assert data['success'] == True
        assert 'data' in data
    
    @pytest.mark.django_db
    def test_available_dates_requires_staff_id(self, client):
        """Endpoint дат требует staff_id"""
        url = '/api/booking/available_dates/'
        response = client.get(url)
        data = response.json()
        assert data['success'] == False
    
    @pytest.mark.django_db
    def test_available_times_requires_params(self, client):
        """Endpoint времени требует staff_id и date"""
        url = '/api/booking/available_times/'
        response = client.get(url)
        data = response.json()
        assert data['success'] == False
```

---

## 6. Известные проблемы и риски

### ⚠️ Критические

| Проблема | Влияние | Решение |
|----------|---------|---------|
| Нет поля `image` в модели Service | Не отобразится картинка | Добавить ImageField или использовать placeholder |
| `yclients_service_id` может быть пустым | Бронирование не сработает | Фильтровать опции без ID |
| Нет URL `/services/<id>/` | 404 | Добавить в urls.py |

### ⚡ Важные

| Проблема | Влияние | Решение |
|----------|---------|---------|
| `options_filtered` не определён в модели | TemplateError | Использовать `options.filter()` во view |
| `options_filtered_count` не определён | Условие не сработает | Передавать `options_count` из view |

---

## 7. Следующие шаги

1. **Сейчас**: Создать минимальный view + URL
2. **Затем**: Добавить базовый шаблон с debug-выводом
3. **Проверить**: Что данные приходят корректно
4. **Потом**: Интегрировать полную вёрстку
5. **Финал**: Тестировать E2E бронирование
