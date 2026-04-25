"""T-06 RED: personalization — get_or_create_bot_user, greet_text, update_context."""
import pytest
from asgiref.sync import sync_to_async
from model_bakery import baker

# transaction=True обязательно для async-тестов с DB:
# обычный django_db использует savepoints через TestCase, что некорректно
# работает в async-контексте (см. code-reviewer review #2).
pytestmark = pytest.mark.django_db(transaction=True)


# baker.make нельзя вызывать из async — оборачиваем
amake = sync_to_async(baker.make, thread_sensitive=True)
aprepare = sync_to_async(baker.prepare, thread_sensitive=True)


# ─── get_or_create_bot_user ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_or_create_new_user():
    from maxbot.personalization import get_or_create_bot_user
    from services_app.models import BotUser
    user, created = await get_or_create_bot_user(max_user_id=111, display_name="Иван")
    assert created is True
    assert user.max_user_id == 111
    assert user.display_name == "Иван"
    assert await BotUser.objects.acount() == 1


@pytest.mark.asyncio
async def test_get_or_create_existing_user_updates_display_name():
    """При повторном вызове — возвращает существующего + обновляет display_name если поменялся."""
    await amake("services_app.BotUser", max_user_id=222, display_name="Старое")
    from maxbot.personalization import get_or_create_bot_user
    user, created = await get_or_create_bot_user(max_user_id=222, display_name="Новое")
    assert created is False
    assert user.display_name == "Новое"


@pytest.mark.asyncio
async def test_get_or_create_preserves_client_name():
    """Если пользователь уже ввёл client_name боту — не перезаписываем из display_name MAX."""
    await amake("services_app.BotUser", max_user_id=333, display_name="DN", client_name="Анна")
    from maxbot.personalization import get_or_create_bot_user
    user, created = await get_or_create_bot_user(max_user_id=333, display_name="DN2")
    assert user.client_name == "Анна"
    assert user.display_name == "DN2"


# ─── greet_text ─────────────────────────────────────────────────────────────

def test_greet_text_without_client_name_returns_new_user_greeting():
    from maxbot.personalization import greet_text
    from services_app.models import BotUser
    bu = BotUser(max_user_id=1, client_name="", display_name="")
    text = greet_text(bu, is_new=True)
    assert "Здравствуйте" in text or "Привет" in text


def test_greet_text_with_client_name_personalizes():
    from maxbot.personalization import greet_text
    from services_app.models import BotUser
    bu = BotUser(max_user_id=1, client_name="Иван")
    text = greet_text(bu, is_new=False)
    assert "Иван" in text


def test_greet_text_fallback_to_display_name_when_no_client_name():
    """Если клиент ещё не назвался боту, но у MAX есть display_name — используем его."""
    from maxbot.personalization import greet_text
    from services_app.models import BotUser
    bu = BotUser(max_user_id=1, client_name="", display_name="MAX_Display")
    text = greet_text(bu, is_new=False)
    assert "MAX_Display" in text


# ─── update_context ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_context_merges_new_keys():
    from maxbot.personalization import update_context
    bu = await amake("services_app.BotUser", max_user_id=4001, context={"a": 1})
    await update_context(bu.id, b=2)
    await _arefresh(bu)
    assert bu.context == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_update_context_overwrites_existing_keys():
    from maxbot.personalization import update_context
    bu = await amake("services_app.BotUser", max_user_id=4002, context={"a": 1})
    await update_context(bu.id, a=99)
    await _arefresh(bu)
    assert bu.context == {"a": 99}


@pytest.mark.asyncio
async def test_append_to_context_list():
    """append_to_context дописывает значение в список под ключом (создавая список если его нет)."""
    from maxbot.personalization import append_to_context
    bu = await amake("services_app.BotUser", max_user_id=4003, context={})
    await append_to_context(bu.id, "services_viewed", "massazh-spiny")
    await append_to_context(bu.id, "services_viewed", "shea-plechi")
    await _arefresh(bu)
    assert bu.context["services_viewed"] == ["massazh-spiny", "shea-plechi"]


@pytest.mark.asyncio
async def test_append_to_context_no_duplicates():
    """Повторный append того же значения — no-op, не плодим дубли."""
    from maxbot.personalization import append_to_context
    bu = await amake("services_app.BotUser", max_user_id=4004, context={"services_viewed": ["a"]})
    await append_to_context(bu.id, "services_viewed", "a")
    await _arefresh(bu)
    assert bu.context["services_viewed"] == ["a"]


# ─── helpers ────────────────────────────────────────────────────────────────

async def _arefresh(instance):
    await sync_to_async(instance.refresh_from_db, thread_sensitive=True)()
