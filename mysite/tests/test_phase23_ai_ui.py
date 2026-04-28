"""T07: ai_ui.py — render action_data → MAX inline keyboard + text."""
from __future__ import annotations

from uuid import uuid4

import pytest


def _conv_id():
    return str(uuid4())


def _kb_payloads(attachments):
    """Извлекает payloads всех CallbackButton'ов из list[Attachment]."""
    out = []
    for att in attachments:
        if att.type != "inline_keyboard":
            continue
        for row in att.payload.buttons:
            for btn in row:
                if hasattr(btn, "payload") and btn.payload:
                    out.append(btn.payload)
    return out


def _kb_texts(attachments):
    """Извлекает text всех CallbackButton'ов."""
    out = []
    for att in attachments:
        if att.type != "inline_keyboard":
            continue
        for row in att.payload.buttons:
            for btn in row:
                if hasattr(btn, "text"):
                    out.append(btn.text)
    return out


# ─── render_action — главный диспетчер ───────────────────────────────────


def test_render_action_dispatches_to_correct_renderer():
    from maxbot.ai_ui import render_action
    text, atts = render_action(
        conversation_id=_conv_id(),
        action_type="ask_clarification",
        action_data={"question": "В какой день?", "options": []},
    )
    assert "В какой день?" in text


def test_render_action_unknown_type_returns_safe_default():
    """Неизвестный action_type не должен падать — fallback на текст."""
    from maxbot.ai_ui import render_action
    text, atts = render_action(
        conversation_id=_conv_id(),
        action_type="weird_unknown",
        action_data={},
    )
    assert text  # не пустой
    assert isinstance(atts, list)


# ─── show_masters ─────────────────────────────────────────────────────────


def test_render_show_masters_lists_masters_with_buttons():
    from maxbot.ai_ui import render_action
    conv_id = _conv_id()
    action_data = {
        "explanation": "По вашему запросу подходят:",
        "masters": [
            {
                "master": {"id": 42, "name": "Анна Иванова",
                          "specialization": "массаж", "services_preview": ["массаж спины"]},
                "match_score": 90,
                "match_reasons": ["опытная", "хорошие отзывы"],
            },
            {
                "master": {"id": 43, "name": "Денис Петров",
                          "specialization": "спортивный", "services_preview": []},
                "match_score": 75, "match_reasons": [],
            },
        ],
    }
    text, atts = render_action(
        conversation_id=conv_id, action_type="show_masters",
        action_data=action_data,
    )
    assert "Анна Иванова" in text
    assert "Денис Петров" in text
    payloads = _kb_payloads(atts)
    # Кнопка для каждого мастера с conv_id и master_id
    assert any(f"cb:ai:pick_master:{conv_id}:42" in p for p in payloads)
    assert any(f"cb:ai:pick_master:{conv_id}:43" in p for p in payloads)


def test_render_show_masters_empty_list_graceful():
    from maxbot.ai_ui import render_action
    text, atts = render_action(
        conversation_id=_conv_id(), action_type="show_masters",
        action_data={"masters": [], "explanation": "—"},
    )
    assert text  # информативная заглушка
    assert "не нашёл" in text.lower() or "нет" in text.lower()


# ─── show_slots ───────────────────────────────────────────────────────────


def test_render_show_slots_with_slots_renders_buttons():
    """Если в action_data есть slots — рендерим кнопки выбора времени."""
    from maxbot.ai_ui import render_action
    conv_id = _conv_id()
    action_data = {
        "master_id": 42, "service_id": 100, "date": "2026-04-30",
        "master_name": "Анна",
        "service_name": "Массаж спины",
        "slots": ["10:00", "11:30", "14:00"],
    }
    text, atts = render_action(
        conversation_id=conv_id, action_type="show_slots",
        action_data=action_data,
    )
    assert "Анна" in text
    assert "Массаж спины" in text or "массаж спины" in text.lower()
    payloads = _kb_payloads(atts)
    button_texts = _kb_texts(atts)
    # 3 кнопки времени с unique payloads
    assert "10:00" in button_texts
    assert "11:30" in button_texts
    assert "14:00" in button_texts
    assert any("cb:ai:pick_slot:" in p for p in payloads)


def test_render_show_slots_without_slots_says_no_availability():
    from maxbot.ai_ui import render_action
    text, atts = render_action(
        conversation_id=_conv_id(), action_type="show_slots",
        action_data={
            "master_id": 42, "service_id": 100, "date": "2026-04-30",
            "master_name": "Анна", "service_name": "Массаж", "slots": [],
        },
    )
    assert "нет" in text.lower() or "свобод" in text.lower() or "занят" in text.lower()


def test_render_show_slots_empty_includes_fallback_buttons():
    """Phase 0: на пустых slots — НЕ тупиковый ответ, а кнопки для альтернатив."""
    from maxbot.ai_ui import render_action
    conv_id = _conv_id()
    text, atts = render_action(
        conversation_id=conv_id, action_type="show_slots",
        action_data={
            "master_id": 42, "service_id": 100, "date": "2026-04-30",
            "master_name": "Анна", "service_name": "Массаж", "slots": [],
        },
    )
    payloads = _kb_payloads(atts)
    button_texts = _kb_texts(atts)
    # 3 fallback кнопки: завтра, через 3 дня, другой мастер
    assert any("cb:ai:suggest_date:" in p and ":+1" in p for p in payloads)
    assert any("cb:ai:suggest_date:" in p and ":+3" in p for p in payloads)
    assert any("cb:ai:suggest_master:" in p for p in payloads)
    # Текст кнопок дружелюбный
    assert any("завтра" in t.lower() for t in button_texts)
    assert any("3 дня" in t for t in button_texts) or any("через" in t.lower() for t in button_texts)
    assert any("мастер" in t.lower() for t in button_texts)


def test_render_show_slots_when_slots_field_missing():
    """Если ai_concierge ещё не enrich'ил slots — graceful placeholder."""
    from maxbot.ai_ui import render_action
    text, atts = render_action(
        conversation_id=_conv_id(), action_type="show_slots",
        action_data={
            "master_id": 42, "service_id": 100, "date": "2026-04-30",
            "master_name": "Анна", "service_name": "Массаж",
        },
    )
    assert text  # не падает


# ─── confirm_booking ──────────────────────────────────────────────────────


def test_render_confirm_booking_shows_summary_and_buttons():
    from maxbot.ai_ui import render_action
    conv_id = _conv_id()
    action_data = {
        "master_id": 42, "service_id": 100,
        "datetime": "2026-04-30T14:00:00+03:00",
        "master_name": "Анна Иванова",
        "service_name": "Массаж спины",
        "price_from": "2500",
        "duration_min": 60,
    }
    text, atts = render_action(
        conversation_id=conv_id, action_type="confirm_booking",
        action_data=action_data,
    )
    assert "Анна Иванова" in text
    assert "Массаж спины" in text
    # Дата/время в человекочитаемом формате
    assert "14:00" in text
    payloads = _kb_payloads(atts)
    assert any(f"cb:ai:confirm:{conv_id}" in p for p in payloads)
    assert any(f"cb:ai:cancel:{conv_id}" in p for p in payloads)


def test_render_confirm_booking_buttons_have_intent_colors():
    """«Да» = POSITIVE (зелёная), «Отмена» = NEGATIVE (красная)."""
    from maxapi.enums.intent import Intent
    from maxbot.ai_ui import render_action
    text, atts = render_action(
        conversation_id=_conv_id(), action_type="confirm_booking",
        action_data={
            "master_id": 1, "service_id": 1,
            "datetime": "2026-04-30T14:00:00+03:00",
            "master_name": "X", "service_name": "Y",
        },
    )
    intents_by_text: dict = {}
    for att in atts:
        if att.type != "inline_keyboard":
            continue
        for row in att.payload.buttons:
            for btn in row:
                if hasattr(btn, "intent"):
                    intents_by_text[btn.text] = btn.intent
    # «Да»/«Подтвердить» — POSITIVE; «Отмена»/«Нет» — NEGATIVE
    assert any(i == Intent.POSITIVE.value or i == "positive"
               for k, i in intents_by_text.items() if "Да" in k or "Подтвер" in k)
    assert any(i == Intent.NEGATIVE.value or i == "negative"
               for k, i in intents_by_text.items() if "Отмен" in k or "Нет" in k)


# ─── show_my_bookings ─────────────────────────────────────────────────────


def test_render_show_my_bookings_with_bookings():
    from maxbot.ai_ui import render_action
    action_data = {
        "filter": "upcoming",
        "bookings": [
            {"datetime": "2026-04-30T14:00:00+03:00",
             "master_name": "Анна", "service_name": "Массаж спины"},
            {"datetime": "2026-05-15T10:00:00+03:00",
             "master_name": "Денис", "service_name": "Спортивный массаж"},
        ],
    }
    text, atts = render_action(
        conversation_id=_conv_id(), action_type="show_my_bookings",
        action_data=action_data,
    )
    assert "Анна" in text
    assert "Денис" in text
    assert "Массаж спины" in text


def test_render_show_my_bookings_empty():
    from maxbot.ai_ui import render_action
    text, atts = render_action(
        conversation_id=_conv_id(), action_type="show_my_bookings",
        action_data={"filter": "upcoming", "bookings": []},
    )
    assert "нет" in text.lower() or "запис" in text.lower()


# ─── ask_clarification ────────────────────────────────────────────────────


def test_render_ask_clarification_with_options_renders_buttons():
    from maxbot.ai_ui import render_action
    conv_id = _conv_id()
    action_data = {
        "question": "В какой день вам удобнее?",
        "options": ["Завтра", "В понедельник", "В выходные"],
    }
    text, atts = render_action(
        conversation_id=conv_id, action_type="ask_clarification",
        action_data=action_data,
    )
    assert "В какой день" in text
    button_texts = _kb_texts(atts)
    assert "Завтра" in button_texts
    assert "В понедельник" in button_texts
    payloads = _kb_payloads(atts)
    assert any(f"cb:ai:answer:{conv_id}:0" in p for p in payloads)


def test_render_ask_clarification_without_options_no_buttons():
    """Если options=[] — только текст вопроса, без кнопок-опций."""
    from maxbot.ai_ui import render_action
    text, atts = render_action(
        conversation_id=_conv_id(), action_type="ask_clarification",
        action_data={"question": "Уточните?", "options": []},
    )
    assert "Уточните" in text
    # Может быть кнопка отмены или back, но не кнопки options
    button_texts = _kb_texts(atts)
    # Не должно быть answer_0 кнопок
    payloads = _kb_payloads(atts)
    assert not any("cb:ai:answer:" in p for p in payloads)
