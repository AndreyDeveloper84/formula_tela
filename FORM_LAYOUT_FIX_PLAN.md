# План исправления верстки формы бронирования

## 🔍 Анализ проблем

### Проблема 1: Grid layout не работает правильно
**Текущее состояние:**
- Элементы формы расположены последовательно, а не в grid 3x2
- CSS класс `.in-form` имеет `grid-template-columns: repeat(3, 1fr)`, но элементы не распределяются правильно

**Ожидаемое поведение:**
- Форма должна быть сеткой 3 колонки × 2 ряда:
  - **Ряд 1:** Длительность | Количество | Мастер
  - **Ряд 2:** Дата | Время | Стоимость

**Причина:**
- Некоторые элементы (например, `time-select-wrapper`) занимают всю ширину из-за CSS правила `grid-column: 1 / -1`
- Нужно убрать это правило для элементов, которые должны быть в grid

### Проблема 2: Неправильное отображение количества
**Текущее состояние:**
- Когда `durations_count == 1 and quantities_count == 1` - показывается input disabled ✅ (правильно)
- Когда `durations_count == 1 and quantities_count > 1` - показывается select ✅ (правильно)
- Когда `durations_count > 1` - показывается select с placeholder ❌ (неправильно)

**Ожидаемое поведение:**
- Если для выбранной длительности только 1 вариант количества (например, "1 процедура"), нужно показывать **input disabled**, а не select
- Select должен показываться только если для выбранной длительности есть несколько вариантов количества

**Причина:**
- Логика проверяет только общее количество вариантов, но не проверяет количество вариантов для конкретной выбранной длительности
- Нужно добавить проверку в JavaScript: после выбора длительности проверять, сколько вариантов количества для этой длительности

## 📋 План изменений

### Этап 1: Исправление CSS для grid layout

**Файл:** `mysite/static/css/main.css` или встроенные стили в шаблоне

**Изменения:**
1. Убрать правило `grid-column: 1 / -1` для элементов, которые должны быть в grid
2. Оставить это правило только для элементов, которые действительно должны занимать всю ширину (например, alert)
3. Убедиться, что `time-select-wrapper` не занимает всю ширину

**Код:**
```css
/* УБРАТЬ из CSS: */
.in-form .form-control,
.in-form .time-select-wrapper,
.in-form .text-def.semi,
.in-form .alert {
    grid-column: 1 / -1; /* Занимает все колонки */
}

/* ИЗМЕНИТЬ на: */
.in-form .alert {
    grid-column: 1 / -1; /* Только alert занимает всю ширину */
}

/* Остальные элементы остаются в grid */
```

### Этап 2: Исправление логики отображения количества в шаблоне

**Файл:** `mysite/website/templates/website/service_detail.html`

**Изменения:**
1. Упростить логику для случая `durations_count > 1`:
   - Всегда показывать select с placeholder "Сначала выберите длительность"
   - JavaScript будет обновлять этот select при выборе длительности
   - Если для выбранной длительности только 1 вариант - JavaScript заменит select на input disabled

**Текущий код (строки 481-488):**
```django
{% else %}
    <!-- Если несколько длительностей - количество будет заполняться динамически -->
    <select 
        id="quantity-select" 
        class="form-select" 
        required>
        <option value="">Сначала выберите длительность</option>
    </select>
{% endif %}
```

**Оставить как есть** - JavaScript уже обрабатывает это правильно через функцию `updateQuantitySelect()`

### Этап 3: Исправление JavaScript логики

**Файл:** `mysite/website/templates/website/service_detail.html` (блок `{% block extra_js %}`)

**Изменения:**
1. В функции `updateQuantitySelect(duration)` добавить проверку:
   - Если для выбранной длительности только 1 вариант количества - показывать input disabled вместо select
   - Если несколько вариантов - показывать select

**Текущий код функции `updateQuantitySelect` (примерно строки 803-852):**
```javascript
function updateQuantitySelect(duration) {
    const quantitySelect = document.getElementById('quantity-select');
    if (!quantitySelect) return;
    
    if (!duration) {
        quantitySelect.innerHTML = '<option value="">Сначала выберите длительность</option>';
        quantitySelect.classList.remove('visible');
        quantitySelect.required = false;
        return;
    }
    
    const durationInt = parseInt(duration);
    const quantities = optionsMap[durationInt] ? Object.keys(optionsMap[durationInt]).map(Number).sort((a, b) => a - b) : [];
    
    if (quantities.length === 0) {
        quantitySelect.innerHTML = '<option value="">Нет доступных вариантов</option>';
        quantitySelect.classList.add('visible');
        quantitySelect.required = false;
        return;
    }
    
    // Показываем select если он был скрыт
    quantitySelect.classList.add('visible');
    quantitySelect.required = true;
    
    // Очищаем и заполняем опциями
    quantitySelect.innerHTML = '<option value="">Выберите количество</option>';
    
    quantities.forEach(qty => {
        const option = optionsMap[durationInt][qty];
        const optionElem = document.createElement('option');
        optionElem.value = qty;
        
        // Формируем текст: "1 процедура" или "5 процедур"
        const unitLabel = option.unitTypeDisplay;
        optionElem.textContent = `${qty} ${getQuantityLabel(qty, unitLabel)}`;
        
        quantitySelect.appendChild(optionElem);
    });
    
    // Если только одно количество - автоматически выбираем его
    if (quantities.length === 1) {
        quantitySelect.value = quantities[0];
        updatePrice();
    } else {
        quantitySelect.value = '';
        updatePrice();
    }
}
```

**Нужно изменить:**
- Если `quantities.length === 1`, заменить select на input disabled
- Если `quantities.length > 1`, оставить select

### Этап 4: Добавление функции замены select на input

**Новая функция:**
```javascript
function replaceQuantitySelectWithInput(quantity, unitTypeDisplay) {
    const quantitySelect = document.getElementById('quantity-select');
    if (!quantitySelect) return;
    
    const parent = quantitySelect.parentElement;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'text-def';
    input.value = `${quantity} ${unitTypeDisplay}`;
    input.disabled = true;
    input.id = 'quantity-display';
    
    const hiddenInput = document.createElement('input');
    hiddenInput.type = 'hidden';
    hiddenInput.id = 'quantity-select';
    hiddenInput.value = quantity;
    
    parent.replaceChild(input, quantitySelect);
    parent.appendChild(hiddenInput);
}

function replaceQuantityInputWithSelect() {
    const quantityDisplay = document.getElementById('quantity-display');
    const quantitySelect = document.getElementById('quantity-select');
    
    if (!quantityDisplay || !quantitySelect || quantitySelect.type !== 'hidden') return;
    
    const parent = quantityDisplay.parentElement;
    const select = document.createElement('select');
    select.id = 'quantity-select';
    select.className = 'form-select';
    select.required = true;
    
    parent.replaceChild(select, quantityDisplay);
    if (quantitySelect.type === 'hidden') {
        parent.removeChild(quantitySelect);
    }
}
```

## ✅ Чеклист изменений

### CSS изменения
- [ ] Убрать `grid-column: 1 / -1` для `.form-control`, `.time-select-wrapper`, `.text-def.semi`
- [ ] Оставить `grid-column: 1 / -1` только для `.alert`
- [ ] Проверить что grid работает правильно (3 колонки, 2 ряда)

### Шаблон изменения
- [ ] Проверить что логика отображения количества корректна
- [ ] Убедиться что все элементы формы имеют правильные классы

### JavaScript изменения
- [ ] Добавить функцию `replaceQuantitySelectWithInput()`
- [ ] Добавить функцию `replaceQuantityInputWithSelect()`
- [ ] Изменить функцию `updateQuantitySelect()` для использования новых функций
- [ ] Обновить функцию обработки изменения длительности

## 🧪 Тестирование

После изменений проверить:
1. ✅ Форма отображается в grid 3x2
2. ✅ Когда только 1 вариант количества - показывается input disabled
3. ✅ Когда несколько вариантов количества - показывается select
4. ✅ При изменении длительности количество обновляется правильно
5. ✅ На мобильных форма в 1 колонку (через media query)

