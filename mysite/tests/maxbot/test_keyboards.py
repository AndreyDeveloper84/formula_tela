"""T-04 RED: keyboard-фабрики для главного меню, услуг, FAQ, подтверждения.

Тесты проверяют структуру клавиатуры через Pydantic-модели SDK:
buttons[row][col] — это Button с .text и (для callback) .payload.

Callback payload convention:
- cb:menu:services|contacts|faq|book — главное меню
- cb:svc:{id}                         — выбор услуги
- cb:faq:{id}                         — выбор FAQ
- cb:back                             — назад в главное меню
- cb:confirm:yes|no                   — подтверждение/отмена заявки
"""
import pytest
from model_bakery import baker

from maxbot import keyboards


def _flatten(markup):
    """Распаковать AttachmentRequest → список всех кнопок (любой ряд)."""
    # У Attachment объекта payload.buttons — list[list[Button]]
    rows = markup.payload.buttons
    return [btn for row in rows for btn in row]


def _payloads(markup):
    return [getattr(b, "payload", None) for b in _flatten(markup)]


def _texts(markup):
    return [b.text for b in _flatten(markup)]


# ─── main_menu_keyboard ─────────────────────────────────────────────────────

def test_main_menu_has_six_buttons():
    """Главное меню: 6 кнопок (5 базовых + 'Мои записи' N1)."""
    kb = keyboards.main_menu_keyboard()
    assert len(_flatten(kb)) == 6


def test_main_menu_payloads():
    kb = keyboards.main_menu_keyboard()
    payloads = set(_payloads(kb))
    assert payloads == {
        "cb:menu:book", "cb:menu:services", "cb:menu:contacts",
        "cb:menu:faq", "cb:menu:ask", "cb:menu:my_bookings",
    }


# ─── services_keyboard ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_services_keyboard_includes_back_to_categories():
    """Back-кнопка теперь ведёт к КАТЕГОРИЯМ (cb:menu:services), не в главное меню."""
    s1 = baker.make("services_app.Service", name="Массаж спины", is_active=True)
    kb = keyboards.services_keyboard([s1])
    assert keyboards.PAYLOAD_MENU_SERVICES in _payloads(kb)


@pytest.mark.django_db
def test_categories_keyboard_includes_back_button():
    cat = baker.make("services_app.ServiceCategory", name="Массаж", is_active=True)
    kb = keyboards.categories_keyboard([cat])
    assert keyboards.PAYLOAD_BACK in _payloads(kb)


@pytest.mark.django_db
def test_categories_keyboard_callback_contains_cat_id():
    cat = baker.make("services_app.ServiceCategory", name="Массаж", is_active=True)
    kb = keyboards.categories_keyboard([cat])
    assert f"{keyboards.PAYLOAD_CAT_PREFIX}{cat.id}" in _payloads(kb)


@pytest.mark.django_db
def test_services_keyboard_callback_contains_service_id():
    s = baker.make("services_app.Service", name="Антицеллюлитный", is_active=True)
    kb = keyboards.services_keyboard([s])
    assert f"cb:svc:{s.id}" in _payloads(kb)


@pytest.mark.django_db
def test_services_keyboard_button_text_contains_service_name():
    s = baker.make("services_app.Service", name="Расслабляющий массаж", is_active=True)
    kb = keyboards.services_keyboard([s])
    assert any("Расслабляющий" in t for t in _texts(kb))


# ─── faq_keyboard ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_faq_keyboard_renders_article_questions():
    a = baker.make("services_app.HelpArticle", question="Как записаться?", answer="...", is_active=True)
    kb = keyboards.faq_keyboard([a])
    assert "Как записаться?" in _texts(kb)
    assert f"cb:faq:{a.id}" in _payloads(kb)


@pytest.mark.django_db
def test_faq_keyboard_includes_back():
    a = baker.make("services_app.HelpArticle", question="Q", answer="A", is_active=True)
    kb = keyboards.faq_keyboard([a])
    assert "cb:back" in _payloads(kb)


# ─── back_to_menu_keyboard ──────────────────────────────────────────────────

def test_back_to_menu_single_button():
    kb = keyboards.back_to_menu_keyboard()
    flat = _flatten(kb)
    assert len(flat) == 1
    assert flat[0].payload == "cb:back"


# ─── confirm_booking_keyboard ───────────────────────────────────────────────

def test_confirm_booking_has_yes_and_no():
    kb = keyboards.confirm_booking_keyboard()
    payloads = set(_payloads(kb))
    assert payloads == {"cb:confirm:yes", "cb:confirm:no"}


# ─── DRF-287 B8: Phase 3 per-user internal gate ─────────────────────────────


@pytest.mark.django_db
def test_keyboard_phase3_internal_visible(settings):
    """Внутренний тестер (max_user_id в PHASE3_INTERNAL_ACCOUNTS) видит кнопку."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = [12345]
    bot_user = baker.make("services_app.BotUser", max_user_id=12345)

    kb = keyboards.main_menu_keyboard(bot_user=bot_user)

    assert keyboards.PAYLOAD_MENU_NUTRITION in _payloads(kb)


@pytest.mark.django_db
def test_keyboard_phase3_internal_hidden(settings):
    """Не-внутренний user (id отсутствует в whitelist) кнопку не видит."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = [12345]
    bot_user = baker.make("services_app.BotUser", max_user_id=99999)

    kb = keyboards.main_menu_keyboard(bot_user=bot_user)

    assert keyboards.PAYLOAD_MENU_NUTRITION not in _payloads(kb)


@pytest.mark.django_db
def test_keyboard_phase3_global_flag_overrides(settings):
    """NUTRITION_ENABLED=True перебивает gate — кнопка видна всем, даже при пустом списке."""
    settings.NUTRITION_ENABLED = True
    settings.PHASE3_INTERNAL_ACCOUNTS = []
    bot_user = baker.make("services_app.BotUser", max_user_id=99999)

    kb = keyboards.main_menu_keyboard(bot_user=bot_user)

    assert keyboards.PAYLOAD_MENU_NUTRITION in _payloads(kb)


def test_keyboard_phase3_no_bot_user_hidden(settings):
    """Defensive: bot_user=None + global flag off → кнопку скрываем."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = [12345]

    kb = keyboards.main_menu_keyboard(bot_user=None)

    assert keyboards.PAYLOAD_MENU_NUTRITION not in _payloads(kb)
