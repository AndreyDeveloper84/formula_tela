"""DRF-246: external_user_id_for() — BotUser → bot:{max_user_id}."""
from __future__ import annotations

import pytest
from model_bakery import baker

from maxbot.services.ayla_user_proxy import external_user_id_for
from services_app.models import BotUser

pytestmark = pytest.mark.django_db


def test_external_id_format_matches_ayla_regex():
    bu = baker.make(BotUser, max_user_id=12345)
    assert external_user_id_for(bu) == "bot:12345"


def test_external_id_stable_across_calls():
    bu = baker.make(BotUser, max_user_id=99999)
    assert external_user_id_for(bu) == external_user_id_for(bu)


def test_external_id_handles_large_max_user_ids():
    """MAX user_id is BigInteger — verify long ids fit Ayla regex (max 64)."""
    bu = baker.make(BotUser, max_user_id=9_007_199_254_740_991)
    ext = external_user_id_for(bu)
    assert ext.startswith("bot:")
    assert len(ext.split(":")[1]) <= 64
