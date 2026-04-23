/* payment-status-poll.js
   Страница /payments/success/ — опрашивает /api/payments/status/?order=...
   каждые 3 секунды до fulfilled=true или таймаута 60 сек.
   Номер заказа берётся из #payment-config[data-order="FT-..."] (раньше это
   был inline-script, блокировался CSP).
*/
(function () {
    "use strict";

    const cfg = document.getElementById("payment-config");
    const orderNumber = cfg ? (cfg.dataset.order || "") : "";
    if (!orderNumber) return;

    const POLL_INTERVAL_MS = 3000;
    const MAX_POLL_MS = 60000;
    const statusEl = document.getElementById("payment-status-text");
    const recordEl = document.getElementById("payment-record");
    const spinnerEl = document.getElementById("payment-spinner");
    const successEl = document.getElementById("payment-success-block");
    const pendingEl = document.getElementById("payment-pending-block");

    const started = Date.now();

    function showSucceeded(data) {
        if (spinnerEl) spinnerEl.style.display = "none";
        if (pendingEl) pendingEl.style.display = "none";
        if (successEl) successEl.style.display = "block";
        if (recordEl && data.yclients_record_id) {
            recordEl.textContent = "№ записи в YClients: " + data.yclients_record_id;
        }
    }

    function showPending(message) {
        if (statusEl) statusEl.textContent = message;
    }

    function poll() {
        fetch("/api/payments/status/?order=" + encodeURIComponent(orderNumber))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data || !data.success) {
                    showPending("Заказ не найден. Обратитесь к администратору.");
                    return;
                }
                if (data.payment_status === "succeeded" && data.fulfilled) {
                    showSucceeded(data);
                    return;
                }
                if (data.payment_status === "canceled") {
                    window.location.href = "/payments/cancelled/?order=" + encodeURIComponent(orderNumber);
                    return;
                }
                if (Date.now() - started > MAX_POLL_MS) {
                    showPending(
                        "Платёж ещё обрабатывается. Мы пришлём уведомление, как только всё будет готово."
                    );
                    return;
                }
                setTimeout(poll, POLL_INTERVAL_MS);
            })
            .catch(function () {
                setTimeout(poll, POLL_INTERVAL_MS);
            });
    }

    poll();
})();
