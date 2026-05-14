"""DRF-292 (B-13) — `maxbot.segmentation.in_phase3_segment` invariants.

Decision tree being tested (top wins; see segmentation.py docstring):

    1. NUTRITION_ENABLED=True                 → True for everyone
    2. max_user_id ∈ PHASE3_INTERNAL_ACCOUNTS → True (always opt-in)
    3. PHASE3_AB_ENABLED=False                → False (no public exposure)
    4. bot_user.id % 100 < 50                 → segment A; else segment B

The bot_user=None branch returns False for every layer (fail-closed default
for code paths that don't have a resolved user yet).
"""
from __future__ import annotations

import pytest
from model_bakery import baker

from maxbot.segmentation import in_phase3_segment


@pytest.mark.django_db
def test_segment_stable_for_same_user(settings):
    """Same `bot_user.id` always lands in the same bucket — no flapping."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_AB_ENABLED = True
    settings.PHASE3_INTERNAL_ACCOUNTS = []

    user = baker.make("services_app.BotUser", max_user_id=42)
    first = in_phase3_segment(user)
    second = in_phase3_segment(user)
    third = in_phase3_segment(user)
    assert first == second == third, "segment must be deterministic per user"


@pytest.mark.django_db
def test_segment_50_50_distribution(settings):
    """1000 users → split within ±10% of 50/50.

    `bot_user.id` is Django PK (monotonic per insertion). Modulo 100 should
    distribute evenly. Tolerance 40-60 captures any future regression that
    biases the split (e.g. accidentally keying on max_user_id).
    """
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_AB_ENABLED = True
    settings.PHASE3_INTERNAL_ACCOUNTS = []

    users = baker.make("services_app.BotUser", _quantity=1000, _bulk_create=True)
    in_a = sum(1 for u in users if in_phase3_segment(u))
    ratio = in_a / len(users)
    assert 0.40 <= ratio <= 0.60, f"50/50 split skewed: segment A = {ratio:.2%}"


@pytest.mark.django_db
def test_segment_internal_account_always_in(settings):
    """Internal cohort opt-in regardless of A/B armed state — they're pilots."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_AB_ENABLED = False  # A/B not armed
    settings.PHASE3_INTERNAL_ACCOUNTS = [777]

    user = baker.make("services_app.BotUser", max_user_id=777)
    assert in_phase3_segment(user) is True


@pytest.mark.django_db
def test_segment_off_no_exposure(settings):
    """A/B OFF + non-internal → False, even if `bot_user.id % 100 < 50` would say A."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_AB_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = []

    # 100 users, every one of them — must all be False because A/B not armed
    users = baker.make("services_app.BotUser", _quantity=100, _bulk_create=True)
    assert all(in_phase3_segment(u) is False for u in users)


@pytest.mark.django_db
def test_segment_global_flag_overrides_everything(settings):
    """NUTRITION_ENABLED=True → True even with A/B OFF + empty internal list."""
    settings.NUTRITION_ENABLED = True
    settings.PHASE3_AB_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = []

    user = baker.make("services_app.BotUser", max_user_id=1)
    assert in_phase3_segment(user) is True


def test_segment_no_bot_user_returns_false(settings):
    """`bot_user=None` is fail-closed at every layer except global flag."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_AB_ENABLED = True
    settings.PHASE3_INTERNAL_ACCOUNTS = [42]

    assert in_phase3_segment(None) is False


def test_segment_global_flag_true_with_no_bot_user(settings):
    """Even with bot_user=None, NUTRITION_ENABLED=True wins (full rollout)."""
    settings.NUTRITION_ENABLED = True
    settings.PHASE3_AB_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = []

    assert in_phase3_segment(None) is True
