"""FSM-состояния для booking-флоу.

Используется встроенный maxapi.context.MemoryContext (per-process in-memory).
См. docs/plans/maxbot-phase1-research.md §5.
"""
from maxapi.context.state_machine import State, StatesGroup


class BookingStates(StatesGroup):
    awaiting_name = State()
    awaiting_phone = State()
    awaiting_confirm = State()
