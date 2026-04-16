import logging

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)


def send_telegram(text: str) -> bool:
    """Отправить сообщение в Telegram-чат. Возвращает True при успехе."""
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(settings, "TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.warning("send_telegram: TELEGRAM_BOT_TOKEN или TELEGRAM_CHAT_ID не настроены")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    proxies = None
    proxy_url = getattr(settings, "TELEGRAM_PROXY", "") or getattr(settings, "OPENAI_PROXY", "")
    if proxy_url:
        proxies = {"https": proxy_url}
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
            proxies=proxies,
        )
        if not r.ok:
            logger.error("send_telegram HTTP %s: %s", r.status_code, r.text[:200])
        return r.ok
    except requests.RequestException as exc:
        logger.error("send_telegram error: %s", exc)
        return False


def send_agent_error_alert(task) -> bool:
    """
    Отправляет Telegram-алерт об ошибке агента.

    Параметр task — объект AgentTask (duck typing).
    Используемые атрибуты: pk, agent_type, get_agent_type_display(), error_message.
    """
    agent_label = task.get_agent_type_display() if hasattr(task, "get_agent_type_display") else task.agent_type
    error_preview = (task.error_message or "Неизвестная ошибка")[:300]

    admin_path = ""
    try:
        admin_path = reverse("admin:agents_agenttask_change", args=[task.pk])
        base_url = getattr(settings, "SITE_BASE_URL", "")
        if base_url:
            admin_path = f"{base_url.rstrip('/')}{admin_path}"
    except Exception:
        pass

    lines = [
        "\u26a0\ufe0f <b>Ошибка агента</b>",
        f"\n<b>Агент:</b> {agent_label}",
        f"<b>Task ID:</b> {task.pk}",
        f"\n<b>Ошибка:</b>\n<code>{error_preview}</code>",
    ]
    if admin_path:
        lines.append(f'\n<a href="{admin_path}">Открыть в админке</a>')

    return send_telegram("\n".join(lines))


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


def notify_new_landing(landing) -> bool:
    """
    Уведомляет в Telegram о новой SEO-посадочной странице для модерации.

    Параметр landing — объект LandingPage (duck typing, без импорта модели).
    Используемые атрибуты: pk, slug, h1, cluster (опционально, может быть None).

    Формирует ссылку на admin-панель:
    - Если SITE_BASE_URL настроен — полный URL
    - Иначе — относительный путь /admin/agents/landingpage/<pk>/change/

    Возвращает True если сообщение отправлено успешно.
    """
    # Admin URL
    admin_path = reverse("admin:agents_landingpage_change", args=[landing.pk])
    base_url = getattr(settings, "SITE_BASE_URL", "")
    if base_url:
        admin_url = f"{base_url.rstrip('/')}{admin_path}"
    else:
        admin_url = admin_path

    # Название кластера (graceful)
    cluster_name = ""
    if hasattr(landing, "cluster") and landing.cluster:
        cluster_name = landing.cluster.name

    lines = [
        "\U0001f4dd <b>Новая SEO-страница на модерацию</b>",
    ]

    if cluster_name:
        lines.append(f"\n\U0001f3af <b>Кластер:</b> {cluster_name}")

    lines.append(f"\n<b>H1:</b> {landing.h1}")
    lines.append(f"<b>Slug:</b> <code>{landing.slug}</code>")
    lines.append(f"\n\U0001f517 <a href=\"{admin_url}\">Открыть в админке</a>")

    # Чеклист модерации
    lines.append(
        "\n<b>Чеклист модерации:</b>\n"
        "\u2610 Title \u2264 70 символов\n"
        "\u2610 Description \u2264 160 символов\n"
        "\u2610 H1 содержит ключевой запрос\n"
        "\u2610 Контент уникален и полезен\n"
        "\u2610 Внутренние ссылки корректны"
    )

    text = "\n".join(lines)
    return send_telegram(text)


def send_weekly_seo_report(report: dict) -> bool:
    """
    Отправляет еженедельный SEO-отчёт в Telegram.

    Структура report:
    {
        "period": str,                    # "17.02 – 23.02.2026"
        "total_clusters": int,
        "total_clicks": int,
        "total_impressions": int,
        "avg_position": float,
        "top_growth": [{"cluster": str, "change": float, "url": str}],
        "top_drops": [{"cluster": str, "change": float, "url": str}],
        "opportunities": [str],           # текстовые рекомендации
        "weekly_plan": [str],             # задачи на неделю
    }

    Все поля опциональны (используется report.get с дефолтами).
    Пустой словарь → возвращает True, send_telegram НЕ вызывается.
    """
    if not report:
        return True

    period = report.get("period", "—")
    total_clusters = report.get("total_clusters", 0)
    total_clicks = report.get("total_clicks", 0)
    total_impressions = report.get("total_impressions", 0)
    avg_position = report.get("avg_position", 0.0)

    lines = [
        f"\U0001f4ca <b>SEO-отчёт за неделю: {period}</b>",
    ]

    # ── Общие метрики ────────────────────────────────────────────────
    lines.append(
        f"\n\U0001f4c8 <b>Общие метрики:</b>\n"
        f"\u2022 Кластеров: {total_clusters}\n"
        f"\u2022 Клики: {total_clicks}\n"
        f"\u2022 Показы: {total_impressions}\n"
        f"\u2022 Средняя позиция: {avg_position:.1f}"
    )

    # ── Лидеры роста ─────────────────────────────────────────────────
    top_growth = report.get("top_growth", [])
    if top_growth:
        lines.append(f"\n\U0001f7e2 <b>Лидеры роста</b> ({len(top_growth)}):")
        for item in top_growth:
            lines.append(
                f"\u2022 <b>{item['cluster']}</b> \u2014 {item['change']:+.1f}%"
                f"\n  <code>{item['url']}</code>"
            )

    # ── Просадки ─────────────────────────────────────────────────────
    top_drops = report.get("top_drops", [])
    if top_drops:
        lines.append(f"\n\U0001f534 <b>Просадки</b> ({len(top_drops)}):")
        for item in top_drops:
            lines.append(
                f"\u2022 <b>{item['cluster']}</b> \u2014 {item['change']:+.1f}%"
                f"\n  <code>{item['url']}</code>"
            )

    # ── Возможности ──────────────────────────────────────────────────
    opportunities = report.get("opportunities", [])
    if opportunities:
        lines.append(f"\n\U0001f4a1 <b>Возможности:</b>")
        for i, opp in enumerate(opportunities, 1):
            lines.append(f"{i}. {opp}")

    # ── План на неделю ───────────────────────────────────────────────
    weekly_plan = report.get("weekly_plan", [])
    if weekly_plan:
        lines.append(f"\n\U0001f4cb <b>План на неделю:</b>")
        for i, task in enumerate(weekly_plan, 1):
            lines.append(f"{i}. {task}")

    text = "\n".join(lines)
    return send_telegram(text)


# ── Retention ────────────────────────────────────────────────────────


def _delta_str(current: float, previous: float, suffix: str = "%") -> str:
    d = current - previous
    icon = "\u2b06\ufe0f" if d >= 0 else "\u2b07\ufe0f"
    sign = "+" if d >= 0 else ""
    return f"{icon} {sign}{d:.1f}{suffix}"


def send_retention_summary(snapshot, previous=None) -> bool:
    """Ежедневный краткий алерт при значимых изменениях удержания."""
    if previous is not None:
        r30_drop = previous.retention_30d - snapshot.retention_30d
        churn_spike = snapshot.churn_rate - previous.churn_rate
        if r30_drop < 10 and churn_spike < 10:
            return True  # нет значимых изменений

    lines = [
        f"\U0001f4ca <b>Удержание клиентов: {snapshot.date}</b>",
        "",
        f"\u2022 Клиентов: {snapshot.total_clients} "
        f"(новых {snapshot.new_clients}, повторных {snapshot.returning_clients})",
        f"\u2022 Удержание 30д: {snapshot.retention_30d:.1f}%"
        + (f" ({_delta_str(snapshot.retention_30d, previous.retention_30d)})" if previous else ""),
        f"\u2022 Средний чек: {snapshot.avg_check:,.0f} руб",
        f"\u2022 Частота: {snapshot.avg_frequency:.1f} визитов/мес",
        f"\u2022 Отток: {snapshot.churn_rate:.1f}% ({snapshot.churn_count} клиентов)"
        + (f" ({_delta_str(snapshot.churn_rate, previous.churn_rate)})" if previous else ""),
    ]
    if previous is not None:
        r30_drop = previous.retention_30d - snapshot.retention_30d
        if r30_drop >= 10:
            lines.append(f"\n\u26a0\ufe0f <b>Удержание упало на {r30_drop:.1f}%!</b>")
        churn_spike = snapshot.churn_rate - previous.churn_rate
        if churn_spike >= 10:
            lines.append(f"\u26a0\ufe0f <b>Отток вырос на {churn_spike:.1f}%!</b>")

    return send_telegram("\n".join(lines))


def send_retention_report(snapshot, previous=None) -> bool:
    """Еженедельный полный отчёт удержания (понедельник)."""
    lines = [
        f"\U0001f4ca <b>Отчёт удержания за неделю: {snapshot.date}</b>",
        "",
        "\U0001f4c8 <b>Ключевые метрики:</b>",
        f"\u2022 Всего клиентов: {snapshot.total_clients}",
        f"\u2022 Новых: {snapshot.new_clients} / Повторных: {snapshot.returning_clients}",
        f"\u2022 Удержание: 30д={snapshot.retention_30d:.1f}% "
        f"| 60д={snapshot.retention_60d:.1f}% "
        f"| 90д={snapshot.retention_90d:.1f}%",
        f"\u2022 Частота: {snapshot.avg_frequency:.1f} визитов/мес",
        f"\u2022 Средний чек: {snapshot.avg_check:,.0f} руб",
        f"\u2022 LTV 180д: {snapshot.avg_ltv_180d:,.0f} руб",
        "",
        "\U0001f4c9 <b>Отток:</b>",
        f"\u2022 Ушедших: {snapshot.churn_count} ({snapshot.churn_rate:.1f}%)",
    ]
    top = snapshot.top_churned_services or []
    if top:
        lines.append("\u2022 Топ-услуги оттока:")
        for item in top[:5]:
            if isinstance(item, dict):
                lines.append(f"  - {item.get('service', '?')}: {item.get('count', 0)}")
            else:
                lines.append(f"  - {item}")
    if previous:
        lines.extend([
            "",
            "\U0001f4ca <b>Динамика (vs прошлая неделя):</b>",
            f"\u2022 R30: {previous.retention_30d:.1f}% \u2192 {snapshot.retention_30d:.1f}%"
            f" ({_delta_str(snapshot.retention_30d, previous.retention_30d)})",
            f"\u2022 Отток: {previous.churn_rate:.1f}% \u2192 {snapshot.churn_rate:.1f}%"
            f" ({_delta_str(snapshot.churn_rate, previous.churn_rate)})",
            f"\u2022 Частота: {previous.avg_frequency:.1f} \u2192 {snapshot.avg_frequency:.1f}"
            f" ({_delta_str(snapshot.avg_frequency, previous.avg_frequency, ' виз/мес')})",
        ])
    return send_telegram("\n".join(lines))
