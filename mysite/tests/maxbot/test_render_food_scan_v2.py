"""Phase 3.1 Part 2A T04: confidence routing в render_food_scan."""
from __future__ import annotations


def test_render_food_scan_high_confidence_has_correct_button():
    """confidence >= 0.7 → best-guess + 4 meal-type кнопки + [✏️ Поправить]."""
    from maxbot.ai_ui import render_food_scan_v2
    from maxbot.keyboards import PAYLOAD_SCAN_CORRECT_MENU

    scan = {
        "id": "s1",
        "dish_name": "Паста с курицей",
        "confidence": 0.85,
        "portion_g": 300,
        "nutrition": {"calories": 520, "protein_g": 35, "fat_g": 18, "carbs_g": 55},
    }

    text, attachments = render_food_scan_v2(scan)

    # Best-guess текст
    assert "Паста" in text
    assert "520" in text  # ккал
    # БЖУ
    assert "35" in text and "18" in text and "55" in text

    # Attachments — keyboard с 4 meal-type + correct button
    payloads = _flatten_payloads(attachments[0])
    # Correct button должен присутствовать (с scan_id или без — гибко)
    assert any(p.startswith(PAYLOAD_SCAN_CORRECT_MENU) for p in payloads)
    # 4 meal-type кнопки тоже на месте
    assert any(p.startswith("cb:nutrition:log:") for p in payloads)


def _flatten_payloads(keyboard):
    out = set()
    rows = (
        getattr(getattr(keyboard, "payload", None), "buttons", None)
        or getattr(keyboard, "buttons", None)
        or getattr(keyboard, "rows", None)
        or []
    )
    for row in rows:
        for btn in row:
            payload = getattr(btn, "payload", None)
            if payload is None:
                callback = getattr(btn, "callback", None)
                payload = getattr(callback, "payload", None) if callback else None
            if payload:
                out.add(payload)
    return out


def test_render_food_scan_low_confidence_shows_retake_buttons():
    """confidence < 0.5 → text «Не разобрала» + кнопки переснять/ввести."""
    from maxbot.ai_ui import render_food_scan_v2
    from maxbot.keyboards import PAYLOAD_SCAN_RETAKE, PAYLOAD_SCAN_MANUAL_INPUT

    scan = {
        "id": "s1",
        "dish_name": "?",
        "confidence": 0.3,  # low
        "nutrition": None,
    }

    text, attachments = render_food_scan_v2(scan)
    assert "разобрала" in text.lower() or "🙈" in text

    payloads = _flatten_payloads(attachments[0])
    assert PAYLOAD_SCAN_RETAKE in payloads
    assert PAYLOAD_SCAN_MANUAL_INPUT in payloads


def test_render_food_scan_borderline_medium_treated_as_high():
    """confidence 0.5-0.7 (medium без alternatives) → как high path."""
    from maxbot.ai_ui import render_food_scan_v2
    from maxbot.keyboards import PAYLOAD_SCAN_CORRECT_MENU

    scan = {
        "id": "s1",
        "dish_name": "Что-то",
        "confidence": 0.6,
        "nutrition": {"calories": 300, "protein_g": 10, "fat_g": 5, "carbs_g": 40},
    }

    text, attachments = render_food_scan_v2(scan)
    assert "Что-то" in text
    payloads = _flatten_payloads(attachments[0])
    # Correct-button присутствует (с scan_id suffix или без — гибко)
    assert any(p.startswith(PAYLOAD_SCAN_CORRECT_MENU) for p in payloads)
