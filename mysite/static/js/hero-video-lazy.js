/**
 * Hero-video deferred loading.
 *
 * Задача: не блокировать первый рендер главной страницы на ~2 МБ hero-video.
 * До срабатывания этого скрипта видео-элемент имеет preload="none" + data-src
 * на source'ах — браузер не делает ни одного запроса за видео.
 *
 * Логика:
 *   1. ждём window.load (все критичные ресурсы уже в кэше / отрисованы);
 *   2. +500мс на idle — уступаем Metrika и прочим третьестепенным скриптам;
 *   3. скрываем Safe-Data пользователей: если navigator.connection.saveData=true
 *      или effectiveType ≤ 2g — видео не грузим вообще, остаётся poster;
 *   4. копируем data-src → src на всех <source>, вызываем video.load(),
 *      затем video.play() для эффекта autoplay (muted + playsinline достаточно
 *      чтобы браузер разрешил автозапуск).
 *
 * Безопасно: модуль idempotent, повторный вызов не дублирует play().
 */
(function () {
    "use strict";

    function isSlowConnection() {
        var c = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
        if (!c) return false;
        if (c.saveData === true) return true;
        var eff = c.effectiveType;
        return eff === "slow-2g" || eff === "2g";
    }

    function activateVideo(video) {
        if (video.dataset.heroActivated === "1") return;
        video.dataset.heroActivated = "1";

        var sources = video.querySelectorAll("source[data-src]");
        sources.forEach(function (s) {
            s.src = s.dataset.src;
        });
        // preload="auto" — iOS Safari требует достаточный буфер для autoplay.
        // metadata недостаточно: iOS ждёт готовности к непрерывному воспроизведению
        // до конца и показывает play-button если данных мало.
        video.preload = "auto";
        video.load();
        // Атрибут autoplay уже в HTML — браузер (iOS и desktop) сам запустит
        // воспроизведение когда буфера хватит. Программный .play() на iOS без
        // user-gesture блокируется и может сломать ожидающий autoplay.
        // На всякий случай пробуем на desktop — iOS просто проглотит.
        try {
            var p = video.play();
            if (p && typeof p.catch === "function") {
                p.catch(function () { /* policy заблокировал — autoplay сам отработает */ });
            }
        } catch (e) { /* старые браузеры без Promise */ }
    }

    function isVisible(el) {
        // Проверяем именно computed display — самый надёжный способ для
        // CSS media-query-based show/hide (.video-pk display:none на mobile,
        // .video-mob display:none на desktop).
        //
        // НЕ используем offsetWidth/offsetHeight: <video preload="none"> до
        // активации может иметь height=0 (нет видеоданных, нет intrinsic
        // dimensions), даже когда CSS его реально показывает — это привело
        // бы к ложному isVisible=false и видео никогда не запустилось бы.
        return getComputedStyle(el).display !== "none";
    }

    function start() {
        if (isSlowConnection()) {
            // На slow-2g/saveData видео не активируем — poster остаётся
            return;
        }
        // На главной два <video> — desktop и mobile, один из них всегда скрыт
        // через CSS media-query. Активируем ТОЛЬКО видимый, иначе браузер
        // качает оба файла (~3.2 МБ суммарно вместо 1.2-2 МБ).
        var videos = document.querySelectorAll("video[data-autoplay-hero]");
        videos.forEach(function (v) {
            if (isVisible(v)) activateVideo(v);
        });
    }

    if (document.readyState === "complete") {
        setTimeout(start, 500);
    } else {
        window.addEventListener("load", function () {
            setTimeout(start, 500);
        }, { once: true });
    }
})();
