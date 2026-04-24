"""T-05 RED: BookingStates — FSM-группа на базе maxapi StatesGroup."""


def test_booking_states_defines_three_states():
    from maxbot.states import BookingStates
    states = BookingStates.states()
    assert len(states) == 3


def test_booking_states_names_are_qualified():
    """Имена в формате 'BookingStates:awaiting_*'."""
    from maxbot.states import BookingStates
    states = BookingStates.states()
    expected = {
        "BookingStates:awaiting_name",
        "BookingStates:awaiting_phone",
        "BookingStates:awaiting_confirm",
    }
    assert set(states) == expected
