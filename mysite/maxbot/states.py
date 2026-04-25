"""FSM-состояния для booking-флоу.

Используется встроенный maxapi.context.MemoryContext (per-process in-memory).
См. docs/plans/maxbot-phase1-research.md §5.
"""
from maxapi.context.state_machine import State, StatesGroup


class BookingStates(StatesGroup):
    awaiting_name = State()
    awaiting_phone = State()
    awaiting_confirm = State()


class AskStates(StatesGroup):
    """FSM для свободного диалога с AI-помощником (T-06c).

    awaiting_question — клиент кликнул «❓ Задать вопрос», ждём текст вопроса.
    После получения ответа state очищается (one-shot).
    """
    awaiting_question = State()
