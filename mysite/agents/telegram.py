import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_telegram(text: str) -> bool:
    """Отправить сообщение в Telegram-чат. Возвращает True при успехе."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("send_telegram: TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не настроены")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if not r.ok:
            logger.error("send_telegram HTTP %s: %s", r.status_code, r.text[:200])
        return r.ok
    except requests.RequestException as exc:
        logger.error("send_telegram error: %s", exc)
        return False


def send_seo_alert(alerts: list[dict]) -> bool:
    """
    Отправляет Telegram-алерт о просадках SEO-кластеров.

    Каждый алерт имеет формат:
    {
        "cluster": str,                        # название кластера
        "type": "click_drop" | "position_drop",
        "change": float,   # % для click_drop, кол-во мест для position_drop
        "current": float,  # текущее значение (клики или позиция)
        "previous": float, # предыдущее значение
        "url": str,        # target_url кластера
    }

    Формирует одно сообщение со всеми алертами, сгруппированными по типу.
    Возвращает True если сообщение отправлено успешно.
    Если алертов нет — не отправляет ничего, возвращает True.
    """
    if not alerts:
        return True

    click_drops = [a for a in alerts if a["type"] == "click_drop"]
    pos_drops   = [a for a in alerts if a["type"] == "position_drop"]

    lines = ["\U0001f53b <b>SEO-алерт: просадки позиций</b>"]

    # ── Просадки кликов ───────────────────────────────────────────────
    if click_drops:
        lines.append(
            f"\n\U0001f4c9 <b>Падение кликов \u226520%</b> ({len(click_drops)} кластеров):"
        )
        for a in sorted(click_drops, key=lambda x: x["change"]):
            lines.append(
                f"\u2022 <b>{a['cluster']}</b> \u2014 {a['change']:+.1f}%"
                f" ({int(a['previous'])} \u2192 {int(a['current'])} кл.)"
                f"\n  <code>{a['url']}</code>"
            )

    # ── Просадки позиций ──────────────────────────────────────────────
    if pos_drops:
        lines.append(
            f"\n\U0001f4cd <b>Ухудшение позиций \u22653 места</b> ({len(pos_drops)} кластеров):"
        )
        for a in sorted(pos_drops, key=lambda x: x["change"], reverse=True):
            lines.append(
                f"\u2022 <b>{a['cluster']}</b> \u2014 +{a['change']:.1f} мест"
                f" (поз. {a['previous']:.1f} \u2192 {a['current']:.1f})"
                f"\n  <code>{a['url']}</code>"
            )

    # ── Что делать ────────────────────────────────────────────────────
    lines.append(
        "\n<b>Что делать:</b>\n"
        "1. Проверь изменения на страницах за неделю\n"
        "2. Обнови Title/Description под запросы\n"
        "3. Проверь индексацию в Яндекс.Вебмастере"
    )

    text = "\n".join(lines)
    return send_telegram(text)
