/* Booking Wizard — модалка записи через форму-мастер */
let wizardData = {
    categoryId: null,
    categoryName: '',
    serviceId: null,
    serviceName: '',
    serviceDetails: '',
    optionId: null,
    masterName: ''
};

let wizardPendingMaster = null;

window.openMasterBooking = function(masterName) {
    wizardPendingMaster = { name: masterName || '' };
    const modalEl = document.getElementById('bookingWizard');
    const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
    modal.show();
};

function wizardShowStep(n) {
    document.querySelectorAll('.wizard-step').forEach(el => el.style.display = 'none');
    document.getElementById('wizLoading').style.display = 'none';
    document.getElementById('wizStep' + n).style.display = 'block';
    document.querySelectorAll('.bp-step').forEach(el => {
        let s = parseInt(el.dataset.step);
        el.style.background = s <= n ? '#222' : '#ddd';
    });
}

function wizardBack(step) {
    wizardShowStep(step);
}

document.addEventListener('DOMContentLoaded', function() {
    // Event delegation — inline onclick="" блокируется CSP (script-src без 'unsafe-inline').
    // Кнопки с классом .js-open-master-booking и data-master-name открывают wizard с
    // преднастроенным мастером (карточки на /masters/ и т.п.).
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.js-open-master-booking');
        if (!btn) return;
        e.preventDefault();
        window.openMasterBooking(btn.dataset.masterName || '');
    });

    const wizardEl = document.getElementById('bookingWizard');
    if (!wizardEl) return;
    wizardEl.addEventListener('show.bs.modal', function() {
        wizardShowStep(1);
        const masterName = wizardPendingMaster ? wizardPendingMaster.name : '';
        wizardPendingMaster = null;
        wizardData = {
            categoryId: null, categoryName: '', serviceId: null, serviceName: '',
            serviceDetails: '', optionId: null, masterName: masterName
        };
        const banner = document.getElementById('wizMasterBanner');
        const bannerName = document.getElementById('wizMasterBannerName');
        if (masterName) {
            banner.style.display = 'block';
            bannerName.textContent = masterName;
        } else {
            banner.style.display = 'none';
        }
        loadCategories();
    });
});

function loadCategories() {
    let container = document.getElementById('wizCategories');
    container.innerHTML = '<p style="color:#888;">Загрузка...</p>';
    fetch('/api/wizard/categories/')
        .then(r => r.json())
        .then(data => {
            container.innerHTML = '';
            if (!data.categories || data.categories.length === 0) {
                container.innerHTML = '<p>Категории не найдены</p>';
                return;
            }
            data.categories.forEach(cat => {
                let btn = document.createElement('button');
                btn.className = 'btn-white2 t-btn';
                btn.style.cssText = 'width:100%;text-align:left;border:1px solid #ddd;cursor:pointer;padding:12px 16px;';
                btn.innerHTML = '<span class="semi">' + cat.name + '</span> <span class="op50" style="float:right;">' + cat.services_count + ' ' + pluralize(cat.services_count) + '</span>';
                btn.onclick = function() { selectCategory(cat.id, cat.name); };
                container.appendChild(btn);
            });
        })
        .catch(() => { container.innerHTML = '<p style="color:red;">Ошибка загрузки</p>'; });
}

function pluralize(n) {
    n = Math.abs(n) % 100;
    if (n >= 11 && n <= 19) return 'услуг';
    let n1 = n % 10;
    if (n1 === 1) return 'услуга';
    if (n1 >= 2 && n1 <= 4) return 'услуги';
    return 'услуг';
}

function selectCategory(catId, catName) {
    wizardData.categoryId = catId;
    wizardData.categoryName = catName;
    document.getElementById('wizCatName').textContent = catName;
    wizardShowStep(2);

    let container = document.getElementById('wizServices');
    container.innerHTML = '<p style="color:#888;">Загрузка...</p>';
    fetch('/api/wizard/categories/' + catId + '/services/')
        .then(r => r.json())
        .then(data => {
            container.innerHTML = '';
            if (!data.services || data.services.length === 0) {
                container.innerHTML = '<p>Услуги не найдены</p>';
                return;
            }
            data.services.forEach(svc => {
                let btn = document.createElement('button');
                btn.className = 'btn-white2 t-btn';
                btn.style.cssText = 'width:100%;text-align:left;border:1px solid #ddd;cursor:pointer;padding:12px 16px;';
                let details = '';
                if (svc.duration && svc.price) {
                    details = svc.duration + ' мин — от ' + svc.price + ' ₽';
                }
                btn.innerHTML = '<span class="semi">' + svc.name + '</span>' + (details ? '<br><span class="op50 f14">' + details + '</span>' : '');
                btn.onclick = function() { selectService(svc.id, svc.name, details, svc.option_id); };
                container.appendChild(btn);
            });
        })
        .catch(() => { container.innerHTML = '<p style="color:red;">Ошибка загрузки</p>'; });
}

function selectService(svcId, svcName, details, optionId) {
    wizardData.serviceId = svcId;
    wizardData.serviceName = svcName;
    wizardData.serviceDetails = details;
    wizardData.optionId = optionId;
    document.getElementById('wizSelectedService').textContent = svcName;
    document.getElementById('wizSelectedDetails').textContent = details;
    document.getElementById('wizError').style.display = 'none';
    wizardShowStep(3);
}

function wizardSubmit() {
    let name = document.getElementById('wizName').value.trim();
    let phone = document.getElementById('wizPhone').value.trim();
    let comment = document.getElementById('wizComment').value.trim();
    let errEl = document.getElementById('wizError');

    if (!name) { errEl.textContent = 'Введите имя'; errEl.style.display = 'block'; return; }
    if (!phone || phone.length < 7) { errEl.textContent = 'Введите корректный телефон'; errEl.style.display = 'block'; return; }

    let btn = document.getElementById('wizSubmitBtn');
    btn.disabled = true;
    btn.textContent = 'Отправка...';

    fetch('/api/wizard/booking/', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': getCSRF()},
        body: JSON.stringify({
            category_id: wizardData.categoryId,
            service_id: wizardData.serviceId,
            option_id: wizardData.optionId,
            master_name: wizardData.masterName || '',
            client_name: name,
            client_phone: phone,
            comment: comment
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            wizardShowStep(4);
            document.getElementById('wizName').value = '';
            document.getElementById('wizPhone').value = '';
            document.getElementById('wizComment').value = '';
        } else {
            errEl.textContent = data.error || 'Ошибка отправки';
            errEl.style.display = 'block';
        }
        btn.disabled = false;
        btn.textContent = 'Записаться';
    })
    .catch(() => {
        errEl.textContent = 'Ошибка сети';
        errEl.style.display = 'block';
        btn.disabled = false;
        btn.textContent = 'Записаться';
    });
}

function getCSRF() {
    let c = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
    return c ? c.split('=')[1] : '';
}
