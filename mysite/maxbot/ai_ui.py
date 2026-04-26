"""Render action_data → MAX inline keyboard + текст сообщения.

См. docs/plans/maxbot-phase2-native-booking.md §T07.

Превращает result от AIConcierge.send_message() в:
- text — что отправить как content в bot.send_message
- attachments — список Attachment (inline keyboards с CallbackButton'ами)

Mapping action_type → render:

| action_type        | Render                                                     |
|--------------------|------------------------------------------------------------|
| show_masters       | «Я нашёл вам:» + список мастеров с CallbackButton'ами     |
| show_slots         | «Свободные времена 27 апр:» + кнопки слотов               |
| confirm_booking    | «X, услуга, дата, время — записать?» + Да/Нет/Изменить    |
| show_my_bookings   | Список будущих/прошлых записей текстом                     |
| ask_clarification  | Вопрос + кнопки options[]                                  |

Callback payloads (стабильный wire-format):
- cb:ai:pick_master:{conv}:{master_id}
- cb:ai:pick_slot:{conv}:{slot_iso}
- cb:ai:confirm:{conv}
- cb:ai:cancel:{conv}
- cb:ai:edit:{conv}
- cb:ai:answer:{conv}:{option_idx}

TODO Phase 2.3 T07:
- render_action(conversation_id, action_type, action_data)
  → tuple[str, list[Attachment]]
- 5 функций render_show_masters, render_show_slots, ..., render_ask_clarification
- Snapshot-тесты test_ai_ui.py с проверкой структуры attachments

Color hints через Intent enum:
- confirm_booking: «Да» = Intent.POSITIVE (зелёная), «Нет» = Intent.NEGATIVE
- остальные = Intent.DEFAULT
"""
from __future__ import annotations
