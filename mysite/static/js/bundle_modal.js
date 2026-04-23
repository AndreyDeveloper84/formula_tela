/* Bundle modal — заявка на комплекс услуг. Вынесено из components/bundle_modal_js.html
   чтобы не нарушать CSP (inline <script> блокируется script-src 'self'). */
(function() {
    'use strict';
    const cfg = document.getElementById('bundle-modal-config');
    const API = cfg ? cfg.dataset.apiBase : location.origin;
    function getCSRF() {
        const c = document.cookie.split(';').find(x => x.trim().startsWith('csrftoken='));
        return c ? c.split('=')[1] : '';
    }
    let curBundleId = null, curBundleName = '', bsModal = null;

    document.addEventListener('DOMContentLoaded', function() {
        const el = document.getElementById('bundleModal');
        if (!el) return;
        bsModal = new bootstrap.Modal(el);
        el.addEventListener('hidden.bs.modal', resetBundleModal);
        document.getElementById('bundle-contact-form').addEventListener('submit', function(e) {
            e.preventDefault();
            submitBundleRequest();
        });

        // Event delegation — inline onclick блокируется CSP. Кнопка бронирования
        // комплекса несёт data-атрибуты, обработчик читает их здесь.
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('.js-open-bundle-modal');
            if (!btn) return;
            e.preventDefault();
            window.openBundleModal(
                parseInt(btn.dataset.bundleId, 10),
                btn.dataset.bundleName || '',
                btn.dataset.price || '',
                btn.dataset.duration || ''
            );
        });
    });

    window.openBundleModal = function(bundleId, bundleName, price, duration) {
        curBundleId = bundleId;
        curBundleName = bundleName;
        document.getElementById('bm-bundle-name').textContent = bundleName;
        document.getElementById('bm-duration').textContent = duration + ' мин';
        document.getElementById('bm-price').textContent = price + ' ₽';
        document.getElementById('bundle-step-1').style.display = 'block';
        document.getElementById('bundle-step-2').style.display = 'none';
        bsModal.show();
    };

    async function submitBundleRequest() {
        const btn = document.getElementById('bm-submit');
        const alertEl = document.getElementById('bm-alert');
        btn.disabled = true; btn.textContent = 'Отправка...'; alertEl.innerHTML = '';

        const name = document.getElementById('bm-name').value.trim();
        const phone = document.getElementById('bm-phone').value.trim();
        const email = document.getElementById('bm-email').value.trim();
        const comment = document.getElementById('bm-comment').value.trim();

        if (!name || !phone) {
            alertEl.innerHTML = '<div class="alert alert-danger">Заполните имя и телефон</div>';
            btn.disabled = false; btn.textContent = 'Отправить заявку'; return;
        }

        const pmEl = document.querySelector('input[name="bundle-payment-method"]:checked');
        const paymentMethod = pmEl ? pmEl.value : 'cash';

        try {
            const r = await fetch(`${API}/api/bundle/request/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCSRF() },
                body: JSON.stringify({
                    bundle_id: curBundleId,
                    bundle_name: curBundleName,
                    name: name, phone: phone, email: email, comment: comment,
                    payment_method: paymentMethod
                })
            });
            const d = await r.json();
            if (d.success) {
                if (d.payment_url) {
                    window.location.href = d.payment_url;
                    return;
                }
                document.getElementById('bundle-step-1').style.display = 'none';
                document.getElementById('bundle-step-2').style.display = 'block';
            } else {
                alertEl.innerHTML = `<div class="alert alert-danger">${d.error || 'Ошибка'}</div>`;
            }
        } catch(e) {
            alertEl.innerHTML = '<div class="alert alert-danger">Ошибка подключения к серверу</div>';
        } finally {
            btn.disabled = false; btn.textContent = 'Отправить заявку';
        }
    }

    function resetBundleModal() {
        curBundleId = null; curBundleName = '';
        document.getElementById('bundle-step-1').style.display = 'block';
        document.getElementById('bundle-step-2').style.display = 'none';
        document.getElementById('bm-name').value = '';
        document.getElementById('bm-phone').value = '';
        document.getElementById('bm-email').value = '';
        document.getElementById('bm-comment').value = '';
        document.getElementById('bm-alert').innerHTML = '';
    }
})();
