/* Форма записи на услугу — service_detail.html */
(function () {
    const _cfg = document.getElementById('booking-js-config');
    const API_BASE_URL = _cfg ? _cfg.dataset.apiBase : '';
    const SERVICE_NAME = _cfg ? _cfg.dataset.serviceName : '';

    const serviceOptions = JSON.parse(
        (document.getElementById('service-options-json') || {}).textContent || '[]'
    );

    let bookingData = {};
    let availableDates = [];
    let datePicker = null;
    let isLoadingDates = false;
    let isLoadingTimes = false;

    const optionsMap = {};
    serviceOptions.forEach(opt => {
        if (!optionsMap[opt.duration]) optionsMap[opt.duration] = {};
        optionsMap[opt.duration][opt.quantity] = opt;
    });

    function getOptionByDurationAndQuantity(duration, quantity) {
        return (optionsMap[duration] && optionsMap[duration][quantity]) || null;
    }
    function formatPrice(price) { return new Intl.NumberFormat('ru-RU').format(price); }
    function formatDate(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' });
    }
    function getCsrfToken() {
        const el = document.querySelector('[name=csrfmiddlewaretoken]');
        if (el) return el.value;
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        return match ? match[1] : '';
    }
    function getQuantityLabel(quantity, unitType) {
        const last = quantity % 10;
        const lastTwo = quantity % 100;
        if (lastTwo >= 11 && lastTwo <= 14) {
            if (unitType === 'процедуры') return 'процедур';
            if (unitType === 'зоны') return 'зон';
            if (unitType === 'визиты') return 'визитов';
            return unitType;
        }
        if (last === 1) {
            if (unitType === 'процедуры') return 'процедура';
            if (unitType === 'зоны') return 'зона';
            if (unitType === 'визиты') return 'визит';
            return unitType;
        }
        if (last >= 2 && last <= 4) return unitType;
        if (unitType === 'процедуры') return 'процедур';
        if (unitType === 'зоны') return 'зон';
        if (unitType === 'визиты') return 'визитов';
        return unitType;
    }
    function groupTimesByPeriod(times) {
        const periods = { 'Утро (9:00 - 12:00)': [], 'День (12:00 - 17:00)': [], 'Вечер (17:00 - 21:00)': [] };
        times.forEach(time => {
            const h = parseInt(time.split(':')[0]);
            if (h >= 9 && h < 12) periods['Утро (9:00 - 12:00)'].push(time);
            else if (h >= 12 && h < 17) periods['День (12:00 - 17:00)'].push(time);
            else if (h >= 17 && h < 21) periods['Вечер (17:00 - 21:00)'].push(time);
        });
        return periods;
    }

    function updatePrice() {
        const durationEl = document.getElementById('duration-select');
        const quantityEl = document.getElementById('quantity-select');
        const priceEl = document.getElementById('price-display');
        const optionEl = document.getElementById('option-select');
        if (!durationEl || !priceEl) return;
        const duration = parseInt(durationEl.value);
        const quantity = parseInt(quantityEl ? quantityEl.value : '');
        if (duration && quantity) {
            const opt = getOptionByDurationAndQuantity(duration, quantity);
            if (opt) {
                priceEl.value = 'Стоимость: ' + formatPrice(opt.price) + ' ₽';
                if (optionEl) optionEl.value = opt.id;
                loadMasters();
                return;
            }
        }
        priceEl.value = 'Стоимость: — ₽';
        if (optionEl) optionEl.value = '';
    }

    function updateQuantityForDuration(duration) {
        const quantityDisplay = document.getElementById('quantity-display');
        const quantitySelect = document.getElementById('quantity-select');
        const allQuantities = new Set();
        Object.values(optionsMap).forEach(dmap => { Object.keys(dmap).forEach(q => allQuantities.add(q)); });
        if (allQuantities.size === 1 && quantityDisplay) { updatePrice(); return; }
        if (!duration) {
            if (quantitySelect && quantitySelect.tagName === 'SELECT') {
                quantitySelect.innerHTML = '<option value="">Сначала выберите длительность</option>';
            }
            updatePrice(); return;
        }
        const durationInt = parseInt(duration);
        const quantities = optionsMap[durationInt]
            ? Object.keys(optionsMap[durationInt]).map(Number).sort((a, b) => a - b) : [];
        if (quantities.length === 0) {
            if (quantitySelect && quantitySelect.tagName === 'SELECT') {
                quantitySelect.innerHTML = '<option value="">Нет доступных вариантов</option>';
            }
            updatePrice(); return;
        }
        if (quantities.length === 1) {
            const opt = optionsMap[durationInt][quantities[0]];
            const oldDisplay = document.getElementById('quantity-display');
            const oldSelect = document.getElementById('quantity-select');
            if (oldDisplay) oldDisplay.remove();
            if (oldSelect) oldSelect.remove();
            const inp = document.createElement('input');
            inp.type = 'text'; inp.className = 'text-def';
            inp.value = quantities[0] + ' ' + getQuantityLabel(quantities[0], opt.unitTypeDisplay);
            inp.disabled = true; inp.id = 'quantity-display';
            const hidden = document.createElement('input');
            hidden.type = 'hidden'; hidden.id = 'quantity-select'; hidden.value = quantities[0];
            const durationEl = document.getElementById('duration-select');
            const insertAfter = durationEl.type === 'hidden' ? durationEl.previousElementSibling : durationEl;
            insertAfter.after(hidden); insertAfter.after(inp);
            updatePrice(); return;
        }
        const oldDisplay = document.getElementById('quantity-display');
        const oldSelect = document.getElementById('quantity-select');
        if (oldDisplay) oldDisplay.remove();
        if (oldSelect) oldSelect.remove();
        const sel = document.createElement('select');
        sel.id = 'quantity-select'; sel.className = 'form-select'; sel.required = true;
        sel.innerHTML = '<option value="">Выберите количество</option>';
        quantities.forEach(qty => {
            const opt = optionsMap[durationInt][qty];
            const o = document.createElement('option');
            o.value = qty; o.textContent = qty + ' ' + getQuantityLabel(qty, opt.unitTypeDisplay);
            sel.appendChild(o);
        });
        const durationEl = document.getElementById('duration-select');
        const insertAfter = durationEl.type === 'hidden' ? durationEl.previousElementSibling : durationEl;
        insertAfter.after(sel);
        updatePrice();
    }

    function resetMasterAndBelow() {
        const masterSelect = document.getElementById('master-select');
        if (masterSelect) { masterSelect.innerHTML = '<option value="">Сначала выберите вариант услуги</option>'; masterSelect.value = ''; }
        resetDateAndBelow();
    }
    function resetDateAndBelow() {
        const dateInput = document.getElementById('date-zapis');
        if (dateInput) { dateInput.value = ''; dateInput.disabled = true; dateInput.placeholder = 'Сначала выберите мастера'; }
        if (datePicker) { try { datePicker.destroy(); } catch(e) {} datePicker = null; }
        availableDates = []; isLoadingDates = false; isLoadingTimes = false;
        resetTimeSelect();
    }
    function resetTimeSelect() {
        const timeSelect = document.getElementById('time-zapis');
        if (timeSelect) { timeSelect.innerHTML = '<option value="">Сначала выберите дату</option>'; timeSelect.disabled = true; }
    }

    async function loadMasters() {
        const optionEl = document.getElementById('option-select');
        if (!optionEl || !optionEl.value) return;
        const serviceOptionId = optionEl.value;
        const select = document.getElementById('master-select');
        select.innerHTML = '<option value="">Загрузка мастеров...</option>'; select.disabled = true;
        try {
            const url = API_BASE_URL + '/api/booking/get_staff/?service_option_id=' + serviceOptionId;
            const resp = await fetch(url);
            const data = await resp.json();
            if (data.success && data.data && data.data.length > 0) {
                select.innerHTML = '<option value="">Выберите мастера</option>';
                data.data.forEach(master => {
                    const o = document.createElement('option');
                    o.value = master.id; o.textContent = master.name || '';
                    if (master.specialization) o.textContent += ' (' + master.specialization + ')';
                    select.appendChild(o);
                });
            } else { select.innerHTML = '<option value="">Нет доступных мастеров</option>'; }
        } catch (err) { select.innerHTML = '<option value="">Ошибка загрузки</option>'; }
        finally { select.disabled = false; resetDateAndBelow(); }
    }

    async function loadAvailableDates(staffId) {
        if (!staffId || isLoadingDates) return;
        isLoadingDates = true;
        try {
            const url = API_BASE_URL + '/api/booking/available_dates/?staff_id=' + staffId;
            const resp = await fetch(url);
            const data = await resp.json();
            if (data.success && data.data && data.data.dates && data.data.dates.length > 0) {
                availableDates = data.data.dates;
                initializeDatePicker(staffId);
            } else {
                const dateInput = document.getElementById('date-zapis');
                if (dateInput) { dateInput.placeholder = 'Нет свободных дат'; dateInput.disabled = true; }
            }
        } catch (err) { console.error('Ошибка загрузки дат:', err); }
        finally { isLoadingDates = false; }
    }

    function initializeDatePicker(staffId) {
        const dateInput = document.getElementById('date-zapis');
        if (!dateInput || !availableDates.length) return;
        if (datePicker) { try { datePicker.destroy(); } catch(e) {} datePicker = null; }
        dateInput.disabled = false; dateInput.placeholder = 'Выберите дату';
        const firstDate = availableDates[0];
        datePicker = flatpickr(dateInput, {
            locale: 'ru', dateFormat: 'Y-m-d', altInput: true, altFormat: 'j F Y (D)',
            minDate: availableDates[0], maxDate: availableDates[availableDates.length - 1],
            enable: availableDates, defaultDate: firstDate, disableMobile: false, allowInput: false, clickOpens: true,
            onChange: function(selectedDates, dateStr) {
                if (!dateStr || !staffId) return;
                resetTimeSelect();
                const timeSelect = document.getElementById('time-zapis');
                if (timeSelect) timeSelect.disabled = false;
                loadAvailableTimes(staffId, dateStr);
            },
            onReady: function() { loadAvailableTimes(staffId, firstDate); }
        });
        if (datePicker) datePicker.open();
    }

    let timesDebounceTimer = null;
    async function loadAvailableTimes(staffId, date) {
        clearTimeout(timesDebounceTimer);
        timesDebounceTimer = setTimeout(() => _loadAvailableTimes(staffId, date), 300);
    }
    async function _loadAvailableTimes(staffId, date) {
        if (isLoadingTimes) return;
        isLoadingTimes = true;
        const timeSelect = document.getElementById('time-zapis');
        const optionEl = document.getElementById('option-select');
        const serviceOptionId = optionEl ? optionEl.value : '';
        timeSelect.disabled = true; timeSelect.innerHTML = '<option value="">Загрузка...</option>';
        try {
            let url = API_BASE_URL + '/api/booking/available_times/?staff_id=' + staffId + '&date=' + date;
            if (serviceOptionId) url += '&service_option_id=' + serviceOptionId;
            const resp = await fetch(url);
            const data = await resp.json();
            if (data.success && data.data && data.data.times && data.data.times.length > 0) {
                const times = data.data.times;
                const grouped = groupTimesByPeriod(times);
                timeSelect.innerHTML = '<option value="">Выберите время</option>';
                for (const [period, periodTimes] of Object.entries(grouped)) {
                    if (periodTimes.length > 0) {
                        const optgroup = document.createElement('optgroup');
                        optgroup.label = period;
                        periodTimes.forEach(time => {
                            const o = document.createElement('option');
                            o.value = time; o.textContent = time;
                            optgroup.appendChild(o);
                        });
                        timeSelect.appendChild(optgroup);
                    }
                }
            } else { timeSelect.innerHTML = '<option value="">На эту дату всё занято</option>'; }
        } catch (err) { timeSelect.innerHTML = '<option value="">Ошибка загрузки</option>'; }
        finally { timeSelect.disabled = false; isLoadingTimes = false; }
    }

    function handleBookingSubmit() {
        const optionEl = document.getElementById('option-select');
        const durationEl = document.getElementById('duration-select');
        const quantityEl = document.getElementById('quantity-select');
        const masterSelect = document.getElementById('master-select');
        const dateInput = document.getElementById('date-zapis');
        const timeSelect = document.getElementById('time-zapis');
        if (!durationEl || !durationEl.value) { alert('Выберите длительность'); return; }
        const quantity = quantityEl ? quantityEl.value : '';
        if (!quantity) { alert('Выберите количество'); return; }
        const serviceOptionId = optionEl ? optionEl.value : '';
        if (!serviceOptionId) { alert('Выберите вариант услуги'); return; }
        if (!masterSelect || !masterSelect.value) { alert('Выберите мастера'); return; }
        const date = dateInput ? dateInput.value : '';
        if (!date) { alert('Выберите дату'); return; }
        const time = timeSelect ? timeSelect.value : '';
        if (!time) { alert('Выберите время'); return; }
        const opt = getOptionByDurationAndQuantity(parseInt(durationEl.value), parseInt(quantity));
        if (!opt) { alert('Ошибка: вариант услуги не найден'); return; }
        const masterName = masterSelect.options[masterSelect.selectedIndex].text;
        bookingData = {
            staff_id: parseInt(masterSelect.value),
            service_ids: [parseInt(opt.yclientsId)],
            date: date, time: time, master_name: masterName,
            service_name: SERVICE_NAME, service_price: opt.price
        };
        document.getElementById('summary-service').textContent = SERVICE_NAME;
        document.getElementById('summary-master').textContent = masterName;
        document.getElementById('summary-datetime').textContent = formatDate(date) + ' в ' + time;
        document.getElementById('summary-price').textContent = formatPrice(opt.price) + ' ₽';
        const modal = new bootstrap.Modal(document.getElementById('contactModal'));
        modal.show();
    }

    async function handleConfirmBooking(e) {
        e.preventDefault();
        const btn = document.getElementById('confirm-booking');
        const originalText = btn.textContent;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Создаём запись...';
        btn.disabled = true;

        const paymentMethodEl = document.querySelector('input[name="payment-method"]:checked');
        const paymentMethod = paymentMethodEl ? paymentMethodEl.value : 'cash';
        const optionIdStr = (document.getElementById('option-select') || {}).value || '';
        const optionId = parseInt(optionIdStr, 10);

        const payload = {
            service_option_id: optionId,
            staff_id: bookingData.staff_id,
            date: bookingData.date,
            time: bookingData.time,
            client_name: document.getElementById('client-name').value.trim(),
            client_phone: document.getElementById('client-phone').value.trim(),
            client_email: document.getElementById('client-email').value.trim(),
            comment: document.getElementById('client-comment').value.trim(),
            payment_method: paymentMethod
        };

        try {
            const resp = await fetch(API_BASE_URL + '/api/services/order/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify(payload)
            });
            const data = await resp.json();
            if (resp.ok && data.success) {
                if (data.payment_method === 'online' && data.payment_url) {
                    window.location.href = data.payment_url;
                    return;
                }
                showModalAlert(data.message || 'Запись подтверждена!', 'success');
                const orderNumber = data.order_number || '';
                setTimeout(() => {
                    window.location.href = '/payments/success/?order=' + encodeURIComponent(orderNumber);
                }, 1500);
            } else {
                let err = data.error || 'Ошибка при создании записи';
                if (data.errors) {
                    const fields = Object.keys(data.errors).join(', ');
                    err = err + ' (' + fields + ')';
                }
                showModalAlert(err, 'danger');
                btn.textContent = originalText;
                btn.disabled = false;
            }
        } catch (err) {
            showModalAlert('Ошибка соединения с сервером', 'danger');
            btn.textContent = originalText;
            btn.disabled = false;
        }
    }

    function showModalAlert(message, type) {
        document.getElementById('modal-alert').innerHTML = '<div class="alert alert-' + type + ' mt-15">' + message + '</div>';
    }

    document.addEventListener('DOMContentLoaded', function() {
        const form = document.getElementById('booking-form');
        if (form) {
            form.addEventListener('change', function(e) {
                const id = e.target.id;
                if (id === 'duration-select') { updateQuantityForDuration(e.target.value); resetMasterAndBelow(); }
                if (id === 'quantity-select') { updatePrice(); }
                if (id === 'master-select') { const staffId = e.target.value; resetDateAndBelow(); if (staffId) loadAvailableDates(staffId); }
            });
        }
        const submitBtn = document.getElementById('submit-booking');
        if (submitBtn) { submitBtn.addEventListener('click', function(e) { e.preventDefault(); handleBookingSubmit(); }); }
        const contactForm = document.getElementById('contact-form');
        if (contactForm) { contactForm.addEventListener('submit', handleConfirmBooking); }
        const durationEl = document.getElementById('duration-select');
        const quantityEl = document.getElementById('quantity-select');
        const optionEl = document.getElementById('option-select');
        if (durationEl && durationEl.value) {
            const duration = parseInt(durationEl.value);
            const quantity = quantityEl ? parseInt(quantityEl.value) : null;
            if (duration && quantity) {
                const opt = getOptionByDurationAndQuantity(duration, quantity);
                if (opt && optionEl) { optionEl.value = opt.id; updatePrice(); }
            }
        }
    });
})();
