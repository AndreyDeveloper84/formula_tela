"""Render action_data → MAX inline keyboard + текст сообщения.

Phase 2.3 §T07. Чистый рендер — никаких network calls / ORM-write'ов.
Принимает action_data dict (готовый, возможно enrich'ed slots/bookings),
возвращает (text, list[Attachment]).

action_type → render function:
  show_masters       → render_show_masters
  show_slots         → render_show_slots
  confirm_booking    → render_confirm_booking
  show_my_bookings   → render_show_my_bookings
  ask_clarification  → render_ask_clarification

Callback payloads (стабильный wire-format для T08 callback handlers):
  cb:ai:pick_master:{conv}:{master_id}
  cb:ai:pick_slot:{conv}:{slot_iso}
  cb:ai:confirm:{conv}
  cb:ai:cancel:{conv}
  cb:ai:edit:{conv}
  cb:ai:answer:{conv}:{option_idx}

Цвета через Intent enum:
  confirm_booking «Да» → POSITIVE (зелёная)
  confirm_booking «Отмена» → NEGATIVE (красная)
  Остальные → DEFAULT (серая)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from maxapi.enums.intent import Intent
from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder


# ─── Callback payload constants ────────────────────────────────────────────


def _payload_pick_master(conv_id: str, master_id: int) -> str:
    return f"cb:ai:pick_master:{conv_id}:{master_id}"


def _payload_pick_slot(conv_id: str, slot_iso: str) -> str:
    return f"cb:ai:pick_slot:{conv_id}:{slot_iso}"


def _payload_confirm(conv_id: str) -> str:
    return f"cb:ai:confirm:{conv_id}"


def _payload_cancel(conv_id: str) -> str:
    return f"cb:ai:cancel:{conv_id}"


def _payload_edit(conv_id: str) -> str:
    return f"cb:ai:edit:{conv_id}"


def _payload_answer(conv_id: str, option_idx: int) -> str:
    return f"cb:ai:answer:{conv_id}:{option_idx}"


def _payload_suggest_date(conv_id: str, offset: str) -> str:
    """Phase 0: fallback при пустых slots → suggest альтернативной даты.

    offset — relative ("+1", "+3", etc) — pseudo-msg «покажи слоты через N дней»
    LLM сам распарсит relative date через today из system_prompt'а.
    """
    return f"cb:ai:suggest_date:{conv_id}:{offset}"


def _payload_suggest_master(conv_id: str) -> str:
    """Phase 0: fallback при пустых slots → подобрать другого мастера."""
    return f"cb:ai:suggest_master:{conv_id}"


def _payload_pick_service(conv_id: str, service_id: int) -> str:
    """Phase 2.4 T02: клик по карточке услуги в recommend_services."""
    return f"cb:ai:pick_service:{conv_id}:{service_id}"


def _payload_food_log(scan_id: str, meal_type: str) -> str:
    """DRF-247: записать скан в дневник питания."""
    return f"cb:nutrition:log:{scan_id}:{meal_type}"


def _payload_food_consent(action: str) -> str:
    """DRF-246: 152-ФЗ согласие на обработку фото."""
    return f"cb:nutrition:consent:{action}"


# ─── render_action — главный диспетчер ───────────────────────────────────


def render_action(
    *,
    conversation_id: str,
    action_type: str,
    action_data: dict[str, Any],
) -> tuple[str, list]:
    """Возвращает (text, list[Attachment]) для send_message.

    Unknown action_type → safe default (текст + нет attachments). Никогда
    не raise — UI всегда должен что-то отдать клиенту.
    """
    conv_id = str(conversation_id)
    if action_type == "show_masters":
        return render_show_masters(conv_id, action_data)
    if action_type == "show_slots":
        return render_show_slots(conv_id, action_data)
    if action_type == "confirm_booking":
        return render_confirm_booking(conv_id, action_data)
    if action_type == "show_my_bookings":
        return render_show_my_bookings(conv_id, action_data)
    if action_type == "recommend_services":
        return render_recommend_services(conv_id, action_data)
    if action_type == "ask_clarification":
        return render_ask_clarification(conv_id, action_data)
    # Unknown — graceful default
    return ("Не получилось разобраться. Попробуйте сформулировать иначе.", [])


# ─── show_masters ──────────────────────────────────────────────────────────


def render_show_masters(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    masters = data.get("masters") or []
    explanation = data.get("explanation") or ""

    if not masters:
        all_busy_date = data.get("all_busy_date") or ""
        if all_busy_date:
            text = (
                f"На {all_busy_date} свободных мастеров нет.\n"
                "Попробовать другой день?"
            )
            builder = InlineKeyboardBuilder()
            builder.row(
                CallbackButton(
                    text="📅 Завтра",
                    payload=_payload_suggest_date(conv_id, "+1"),
                ),
                CallbackButton(
                    text="📆 Через 3 дня",
                    payload=_payload_suggest_date(conv_id, "+3"),
                ),
            )
            builder.row(CallbackButton(
                text="📅 Через неделю",
                payload=_payload_suggest_date(conv_id, "+7"),
            ))
            return (text, [builder.as_markup()])
        return ("К сожалению, не нашёл подходящих мастеров под ваш запрос.", [])

    lines: list[str] = []
    if explanation:
        lines.append(explanation)
        lines.append("")
    for idx, item in enumerate(masters, 1):
        m = item.get("master", {})
        name = m.get("name", "—")
        spec = m.get("specialization", "")
        # categories_preview — список направлений (DRF-categories-fix);
        # services_preview — старый ключ из исторических Message.action_data,
        # читаем его как fallback чтобы не сломать рендер старых диалогов.
        categories = m.get("categories_preview") or m.get("services_preview") or []
        categories_text = ", ".join(categories[:4]) if categories else ""
        score = item.get("match_score")
        reasons = item.get("match_reasons") or []

        line = f"{idx}. {name}"
        if spec:
            line += f" — {spec}"
        if score is not None:
            line += f" (★{score}%)"
        lines.append(line)
        if categories_text:
            lines.append(f"   Направления: {categories_text}")
        if reasons:
            lines.append(f"   {'; '.join(reasons[:2])}")

    builder = InlineKeyboardBuilder()
    for item in masters:
        m = item.get("master", {})
        mid = m.get("id")
        name = m.get("name", "—")
        if mid is None:
            continue
        builder.row(CallbackButton(
            text=f"💆 {name}",
            payload=_payload_pick_master(conv_id, mid),
        ))

    return ("\n".join(lines), [builder.as_markup()])


# ─── show_slots ────────────────────────────────────────────────────────────


def render_show_slots(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    master_name = data.get("master_name") or "мастер"
    service_name = data.get("service_name") or "услуга"
    date_str = data.get("date") or ""
    slots = data.get("slots")

    # Slots field отсутствует — placeholder (concierge ещё не enrich'ил)
    if slots is None:
        return (
            f"{master_name} — {service_name}, {date_str}.\n"
            "Загружаю свободное время…",
            [],
        )

    # Slots empty — нет свободных. Phase 0: НЕ тупик, а fallback-кнопки.
    if not slots:
        text = (
            f"{master_name} — {service_name}, {date_str}.\n"
            "К сожалению, свободных слотов на эту дату нет.\n"
            "Хотите попробовать другой день или мастера?"
        )
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(
                text="📅 На завтра",
                payload=_payload_suggest_date(conv_id, "+1"),
            ),
            CallbackButton(
                text="📆 Через 3 дня",
                payload=_payload_suggest_date(conv_id, "+3"),
            ),
        )
        builder.row(CallbackButton(
            text="👥 Другой мастер",
            payload=_payload_suggest_master(conv_id),
        ))
        return (text, [builder.as_markup()])

    lines = [
        f"{master_name} — {service_name}",
        f"Свободное время {date_str}:",
    ]
    builder = InlineKeyboardBuilder()
    # Группируем по 3 кнопки в ряду — компактная сетка времён
    row_buttons: list[CallbackButton] = []
    for slot in slots:
        slot_str = str(slot)
        # slot — может быть "10:00" или ISO. Оба ок для payload.
        row_buttons.append(CallbackButton(
            text=slot_str,
            payload=_payload_pick_slot(conv_id, slot_str),
        ))
        if len(row_buttons) == 3:
            builder.row(*row_buttons)
            row_buttons = []
    if row_buttons:
        builder.row(*row_buttons)

    return ("\n".join(lines), [builder.as_markup()])


# ─── confirm_booking ──────────────────────────────────────────────────────


def render_confirm_booking(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    master_name = data.get("master_name") or "мастер"
    service_name = data.get("service_name") or "услуга"
    datetime_str = data.get("datetime") or ""
    price_from = data.get("price_from")
    duration_min = data.get("duration_min")

    # Парсим datetime для вывода — fallback на raw если что-то странное
    pretty_when = datetime_str
    try:
        dt = datetime.fromisoformat(datetime_str)
        pretty_when = dt.strftime("%d.%m.%Y в %H:%M")
    except (ValueError, TypeError):
        pass

    lines = [
        "Проверьте детали записи:",
        "",
        f"💆 Мастер: {master_name}",
        f"📋 Услуга: {service_name}",
        f"📅 Когда: {pretty_when}",
    ]
    if duration_min:
        lines.append(f"⏱️ Длительность: {duration_min} мин")
    if price_from:
        lines.append(f"💰 Стоимость: от {price_from} ₽")
    lines.append("")
    lines.append("Подтвердить запись?")

    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="✅ Да, записать",
            payload=_payload_confirm(conv_id),
            intent=Intent.POSITIVE,
        ),
        CallbackButton(
            text="❌ Отмена",
            payload=_payload_cancel(conv_id),
            intent=Intent.NEGATIVE,
        ),
    )
    builder.row(CallbackButton(
        text="✏️ Изменить",
        payload=_payload_edit(conv_id),
    ))

    return ("\n".join(lines), [builder.as_markup()])


# ─── show_my_bookings ─────────────────────────────────────────────────────


def render_show_my_bookings(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    filter_value = data.get("filter") or "upcoming"
    bookings = data.get("bookings")

    # Поле bookings отсутствует — placeholder
    if bookings is None:
        return ("Загружаю ваши записи…", [])

    if not bookings:
        msg = {
            "upcoming": "У вас пока нет предстоящих записей.",
            "past": "У вас пока нет прошедших записей.",
            "all": "У вас пока нет записей.",
        }.get(filter_value, "У вас пока нет записей.")
        return (msg, [])

    title = {
        "upcoming": "Ваши предстоящие записи:",
        "past": "Ваши прошедшие записи:",
        "all": "Ваши записи:",
    }.get(filter_value, "Ваши записи:")
    lines = [title, ""]

    for b in bookings:
        master_name = b.get("master_name") or "—"
        service_name = b.get("service_name") or "—"
        when = b.get("datetime") or ""
        try:
            dt = datetime.fromisoformat(when)
            pretty = dt.strftime("%d.%m.%Y %H:%M")
        except (ValueError, TypeError):
            pretty = when
        lines.append(f"• {pretty} — {master_name}, {service_name}")

    return ("\n".join(lines), [])


# ─── recommend_services (Phase 2.4 T02) ───────────────────────────────────


def render_recommend_services(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    """2-4 услуги из handle_recommend_services — текст + inline-кнопки.

    Текст: explanation от LLM + список услуг (название, длительность, цена).
    Кнопки: по 1 на услугу, payload cb:ai:pick_service:{conv}:{id}.
    Клик → run_ai_turn с pseudo-text «выбираю [name]» → бот вызовет show_masters
    для этой услуги.
    """
    explanation = (data.get("explanation") or "").strip()
    services = data.get("services") or []

    if not services:
        # Не должно случаться (handler возвращает fallback ask_clarification),
        # но на всякий случай:
        return ("Не нашлось подходящих услуг под этот запрос.", [])

    lines = []
    if explanation:
        lines.append(explanation)
        lines.append("")

    for svc in services:
        name = svc.get("name") or "Услуга"
        price = svc.get("price_from")
        duration = svc.get("duration_min")
        category = svc.get("category") or ""
        meta_parts = []
        if duration:
            meta_parts.append(f"{duration} мин")
        if price:
            meta_parts.append(f"от {price} ₽")
        meta = " · ".join(meta_parts)
        cat_suffix = f" [{category}]" if category else ""
        health_suffix = " ⚠️" if svc.get("requires_health_check") else ""
        line = f"💆 {name}{cat_suffix}{health_suffix}"
        if meta:
            line += f" — {meta}"
        lines.append(line)
        sd = (svc.get("short_description") or "").strip()
        if sd:
            lines.append(f"   _{sd}_")

    builder = InlineKeyboardBuilder()
    for svc in services:
        sid = svc.get("id")
        name = (svc.get("name") or "Услуга")[:50]
        if sid is None:
            continue
        builder.row(CallbackButton(
            text=name,
            payload=_payload_pick_service(conv_id, int(sid)),
        ))

    return ("\n".join(lines), [builder.as_markup()])


# ─── ask_clarification ────────────────────────────────────────────────────


def render_ask_clarification(conv_id: str, data: dict[str, Any]) -> tuple[str, list]:
    question = (data.get("question") or "Уточните, пожалуйста?").strip()
    options = data.get("options") or []

    if not options:
        # Только текст вопроса, без кнопок — клиент ответит свободно
        return (question, [])

    builder = InlineKeyboardBuilder()
    for idx, opt in enumerate(options[:5]):  # макс 5 опций per схема
        builder.row(CallbackButton(
            text=str(opt),
            payload=_payload_answer(conv_id, idx),
        ))
    return (question, [builder.as_markup()])


# ─── food_scan (DRF-246) ──────────────────────────────────────────────────


def render_loading_card() -> str:
    """Loading-card text для photo scan: edit-message pattern (Design §5.1).

    Сначала шлём это, получаем message_id, потом edit на финал.
    """
    return "👀 Распознаю..."


def render_food_consent_request() -> tuple[str, list]:
    """152-ФЗ consent prompt — first time user tries to scan food.

    Bot blocks scan until user clicks «Согласен». Stored as
    BotUser.food_scanner_consent_at timestamp.
    """
    text = (
        "📸 Чтобы распознавать еду на фото, я отправлю фото на серверы "
        "OpenAI / Yandex (распознавание блюд + расчёт КБЖУ).\n\n"
        "Фото хранится 30 дней, потом удаляется. Согласно 152-ФЗ нужно "
        "ваше согласие."
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="✅ Согласен",
            payload=_payload_food_consent("agree"),
            intent=Intent.POSITIVE,
        ),
        CallbackButton(
            text="✖ Отказаться",
            payload=_payload_food_consent("decline"),
            intent=Intent.NEGATIVE,
        ),
    )
    return (text, [builder.as_markup()])


def render_food_scan(scan: dict[str, Any]) -> tuple[str, list]:
    """Render FoodScanResponse → MAX message + inline keyboard.

    `scan` is the JSON from `NutritionClient.ScanResponse.raw` (the `data`
    envelope from Ayla). Buttons offer to log this scan into the user's
    food diary (DRF-247) by meal type — meal_type autodetect happens
    callback-side based on current local time.
    """
    dish = scan.get("dish_name") or "Не уверена"
    confidence = float(scan.get("confidence") or 0.0)
    portion_g = scan.get("portion_g")
    nutrition = scan.get("nutrition") or {}
    scan_id = str(scan.get("id") or scan.get("scan_id") or "")

    lines = [f"🍽 {dish}"]
    if confidence:
        lines.append(f"Уверенность: {int(confidence * 100)}%")
    if portion_g:
        lines.append(f"Порция: ~{int(portion_g)}г")

    if nutrition:
        kcal = nutrition.get("calories")
        protein = nutrition.get("protein_g")
        fat = nutrition.get("fat_g")
        carbs = nutrition.get("carbs_g")
        macro_parts = []
        if kcal is not None:
            macro_parts.append(f"{int(kcal)} ккал")
        if protein is not None:
            macro_parts.append(f"Б {protein:.0f}г")
        if fat is not None:
            macro_parts.append(f"Ж {fat:.0f}г")
        if carbs is not None:
            macro_parts.append(f"У {carbs:.0f}г")
        if macro_parts:
            lines.append(" · ".join(macro_parts))
    else:
        lines.append("(КБЖУ не определились — уточните порцию вручную)")

    builder = InlineKeyboardBuilder()
    if scan_id:
        builder.row(
            CallbackButton(
                text="🍳 Завтрак",
                payload=_payload_food_log(scan_id, "breakfast"),
            ),
            CallbackButton(
                text="🍲 Обед",
                payload=_payload_food_log(scan_id, "lunch"),
            ),
        )
        builder.row(
            CallbackButton(
                text="🍽 Ужин",
                payload=_payload_food_log(scan_id, "dinner"),
            ),
            CallbackButton(
                text="☕ Перекус",
                payload=_payload_food_log(scan_id, "snack"),
            ),
        )
    return ("\n".join(lines), [builder.as_markup()] if scan_id else [])


# ─── food_scan_v2 (Phase 3.1 Part 2A T04) ────────────────────────────────


def render_food_scan_v2(scan: dict[str, Any]) -> tuple[str, list]:
    """Phase 3.1 Part 2A: confidence-routed render food scan.

    Confidence >= 0.7  → high path: best-guess + 4 meal-type + [✏️ Поправить]
    Confidence <  0.5  → low path: «Не разобрала 🙈» + [📸 Переснять][✏️ Напишу]
    Confidence 0.5-0.7 → треатим как high (medium с alternatives — Phase 3.2,
                                          требует расширения Ayla scan response)

    Replaces existing `render_food_scan` (которая не имела confidence
    routing и correct-button).
    """
    from maxbot.keyboards import food_scan_low_confidence_keyboard

    confidence = float(scan.get("confidence") or 0.0)

    if confidence < 0.5:
        return _render_food_scan_low_confidence(scan), [
            food_scan_low_confidence_keyboard(),
        ]

    return _render_food_scan_high_confidence(scan)


def _render_food_scan_high_confidence(scan: dict[str, Any]) -> tuple[str, list]:
    from maxbot.keyboards import PAYLOAD_SCAN_CORRECT_MENU

    dish = scan.get("dish_name") or "Не уверена"
    confidence = float(scan.get("confidence") or 0.0)
    portion_g = scan.get("portion_g")
    nutrition = scan.get("nutrition") or {}
    scan_id = str(scan.get("id") or scan.get("scan_id") or "")

    lines = [f"🍽 {dish}"]
    if confidence:
        lines.append(f"Уверенность: {int(confidence * 100)}%")
    if portion_g:
        lines.append(f"Порция: ~{int(portion_g)}г")

    if nutrition:
        kcal = nutrition.get("calories")
        protein = nutrition.get("protein_g")
        fat = nutrition.get("fat_g")
        carbs = nutrition.get("carbs_g")
        macro_parts = []
        if kcal is not None:
            macro_parts.append(f"≈{int(kcal)} ккал")
        if protein is not None:
            macro_parts.append(f"Б {protein:.0f}г")
        if fat is not None:
            macro_parts.append(f"Ж {fat:.0f}г")
        if carbs is not None:
            macro_parts.append(f"У {carbs:.0f}г")
        if macro_parts:
            lines.append(" · ".join(macro_parts))
    else:
        lines.append("(КБЖУ не определились — уточни порцию вручную)")

    builder = InlineKeyboardBuilder()
    if scan_id:
        builder.row(
            CallbackButton(
                text="🍳 Завтрак",
                payload=_payload_food_log(scan_id, "breakfast"),
            ),
            CallbackButton(
                text="🍲 Обед",
                payload=_payload_food_log(scan_id, "lunch"),
            ),
        )
        builder.row(
            CallbackButton(
                text="🍽 Ужин",
                payload=_payload_food_log(scan_id, "dinner"),
            ),
            CallbackButton(
                text="☕ Перекус",
                payload=_payload_food_log(scan_id, "snack"),
            ),
        )
        # Correct button — открывает correction-menu (T07+)
        builder.row(
            CallbackButton(
                text="✏️ Поправить",
                payload=PAYLOAD_SCAN_CORRECT_MENU + ":" + scan_id,
            ),
        )
    return ("\n".join(lines), [builder.as_markup()] if scan_id else [])


def _render_food_scan_low_confidence(scan: dict[str, Any]) -> str:
    """Low confidence (<0.5) — «Не разобрала, переснять или ввести»."""
    return (
        "🙈 Не разобрала, что на фото.\n\n"
        "Попробуй переснять под лучшим светом или впиши блюдо текстом."
    )


# ─── food_logged footer (Phase 3.1 Part 2A T06) ──────────────────────────


def render_food_logged_with_footer(
    meal_label: str, dish_name: str, kcal: int,
) -> tuple[str, list]:
    """Подтверждение записи блюда + footer next-step buttons (Design §5.3).

    [💧 Добавить воду] — заглушка Part 2B (handler ответит «Скоро будет»).
    [📊 Посмотреть день] — открывает /дневник flow.
    """
    from maxbot.keyboards import (
        PAYLOAD_NUTRITION_ADD_WATER,
        PAYLOAD_NUTRITION_VIEW_DAY,
    )

    text = f"✅ Записала {meal_label}: {dish_name} ({kcal} ккал)."

    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="💧 Добавить воду", payload=PAYLOAD_NUTRITION_ADD_WATER),
        CallbackButton(text="📊 Посмотреть день", payload=PAYLOAD_NUTRITION_VIEW_DAY),
    )
    return (text, [builder.as_markup()])


# ─── /дневник daily summary (DRF-247) ──────────────────────────────────────


def render_daily_summary(summary: dict[str, Any]) -> str:
    """Format `data` envelope from /nutrition/internal/summary/ as text.

    No inline keyboard — main menu is appended by send_with_main_menu.
    """
    date_str = summary.get("date") or "сегодня"
    cals_total = summary.get("calories_total") or 0
    cals_goal = summary.get("calories_goal") or 0
    protein = summary.get("protein_g") or 0
    fat = summary.get("fat_g") or 0
    carbs = summary.get("carbs_g") or 0
    entries = summary.get("entries") or []

    lines = [f"📔 Дневник за {date_str}"]
    if not entries:
        lines.append("")
        lines.append("Сегодня записей нет. Сфотографируй еду и нажми кнопку под скана-карточкой.")
        return "\n".join(lines)

    lines.append("")
    by_meal: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        meal = e.get("meal_type") or "snack"
        by_meal.setdefault(meal, []).append(e)
    meal_labels = {
        "breakfast": "🍳 Завтрак",
        "lunch": "🍲 Обед",
        "dinner": "🍽 Ужин",
        "snack": "☕ Перекус",
    }
    for key in ("breakfast", "lunch", "dinner", "snack"):
        rows = by_meal.get(key) or []
        if not rows:
            continue
        lines.append(f"{meal_labels[key]}:")
        for r in rows:
            dish = r.get("dish_name") or "—"
            kcal = int(r.get("calories") or 0)
            lines.append(f"  • {dish} ({kcal} ккал)")

    lines.append("")
    lines.append(
        f"Итого: {int(cals_total)}/{cals_goal or '—'} ккал · "
        f"Б {protein:.0f}г · Ж {fat:.0f}г · У {carbs:.0f}г"
    )
    return "\n".join(lines)
