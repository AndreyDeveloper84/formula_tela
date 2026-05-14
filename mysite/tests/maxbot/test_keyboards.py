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

def test_main_menu_has_six_buttons_when_nutrition_disabled(settings):
    """Главное меню без nutrition: 6 базовых кнопок (default OFF)."""
    settings.NUTRITION_ENABLED = False
    kb = keyboards.main_menu_keyboard()
    assert len(_flatten(kb)) == 6


def test_main_menu_has_eight_buttons_when_nutrition_enabled(settings):
    """Главное меню с nutrition: 8 кнопок (6 базовых + 🍎 Дневник + 💧 Вода — B24)."""
    settings.NUTRITION_ENABLED = True
    kb = keyboards.main_menu_keyboard()
    assert len(_flatten(kb)) == 8


def test_main_menu_payloads_when_nutrition_disabled(settings):
    """Default OFF — payload nutrition отсутствует."""
    settings.NUTRITION_ENABLED = False
    kb = keyboards.main_menu_keyboard()
    payloads = set(_payloads(kb))
    assert payloads == {
        "cb:menu:book", "cb:menu:services", "cb:menu:contacts",
        "cb:menu:faq", "cb:menu:ask", "cb:menu:my_bookings",
    }


def test_main_menu_payloads_when_nutrition_enabled(settings):
    """B24: с включённым nutrition — также появляется 💧 Вода (peer кнопка)."""
    settings.NUTRITION_ENABLED = True
    kb = keyboards.main_menu_keyboard()
    payloads = set(_payloads(kb))
    assert payloads == {
        "cb:menu:book", "cb:menu:services", "cb:menu:contacts",
        "cb:menu:faq", "cb:menu:ask", "cb:menu:my_bookings",
        "cb:menu:nutrition",
        "cb:nutrition:water:add",  # B24: quick-access water
    }


def test_main_menu_includes_nutrition_button_when_enabled(settings):
    """NUTRITION_ENABLED=True → '🍎 Дневник питания' видна в текстах кнопок."""
    settings.NUTRITION_ENABLED = True
    kb = keyboards.main_menu_keyboard()
    texts = _texts(kb)
    nutrition_buttons = [t for t in texts if "Дневник питания" in t]
    assert len(nutrition_buttons) == 1, f"expected 1 nutrition button, got {nutrition_buttons}"


# ─── DRF-287 (B-8) — per-user internal-list gate ────────────────────────────
# Мы передаём `bot_user=` в keyboard factory, оно делегирует в
# `maxbot.segmentation.in_phase3_segment`. Здесь только integration —
# unit-tests на segmentation сами в test_segmentation.py.


@pytest.mark.django_db
def test_main_menu_internal_account_sees_nutrition_button(settings):
    """`bot_user.max_user_id` ∈ PHASE3_INTERNAL_ACCOUNTS → кнопка видна."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_AB_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = [12345]
    bot_user = baker.make("services_app.BotUser", max_user_id=12345)
    kb = keyboards.main_menu_keyboard(bot_user=bot_user)
    assert "cb:menu:nutrition" in set(_payloads(kb))


@pytest.mark.django_db
def test_main_menu_non_internal_account_no_nutrition_button(settings):
    """Не-internal user + AB OFF → кнопка скрыта."""
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_AB_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = [12345]
    bot_user = baker.make("services_app.BotUser", max_user_id=99999)
    kb = keyboards.main_menu_keyboard(bot_user=bot_user)
    assert "cb:menu:nutrition" not in set(_payloads(kb))


def test_main_menu_no_bot_user_hides_nutrition_button(settings):
    """`bot_user=None` (default) + global flag OFF → fail-closed, кнопка скрыта.

    Защищает code paths, у которых нет resolved BotUser к моменту рендера
    (early /start before persist), от случайной утечки фичи.
    """
    settings.NUTRITION_ENABLED = False
    settings.PHASE3_INTERNAL_ACCOUNTS = [12345]
    kb = keyboards.main_menu_keyboard()
    assert "cb:menu:nutrition" not in set(_payloads(kb))


def test_nutrition_welcome_keyboard_has_three_buttons():
    """Phase 3 T01: welcome дневника = 'Попробовать сразу' / 'Настроить' / 'Назад'."""
    kb = keyboards.nutrition_welcome_keyboard()
    payloads = set(_payloads(kb))
    assert payloads == {
        "cb:nutrition:try_now",
        "cb:nutrition:start_anketa",
        "cb:back",
    }


# ─── B24: Quick-access 💧 Вода в main_menu (DRF-303) ───────────────────────


def test_main_menu_water_button_visible_when_nutrition_enabled(settings):
    """B24: при включённом nutrition в main_menu есть И «🍎 Дневник», И «💧 Вода»."""
    settings.NUTRITION_ENABLED = True
    kb = keyboards.main_menu_keyboard()
    payloads = set(_payloads(kb))
    assert keyboards.PAYLOAD_MENU_NUTRITION in payloads
    assert keyboards.PAYLOAD_NUTRITION_ADD_WATER in payloads


def test_main_menu_water_button_hidden_when_nutrition_disabled(settings):
    """B24: при выключенном nutrition обе кнопки скрыты — quick-access идёт под общим gate."""
    settings.NUTRITION_ENABLED = False
    kb = keyboards.main_menu_keyboard()
    payloads = set(_payloads(kb))
    assert keyboards.PAYLOAD_MENU_NUTRITION not in payloads
    assert keyboards.PAYLOAD_NUTRITION_ADD_WATER not in payloads


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
