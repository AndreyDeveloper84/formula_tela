"""
Юнит-тесты моделей: методы, свойства, __str__.
"""
import datetime
import pytest
from decimal import Decimal
from model_bakery import baker


# ─── Service ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_service_str():
    svc = baker.make("services_app.Service", name="Антицеллюлитный массаж")
    assert str(svc) == "Антицеллюлитный массаж"


# ─── ServiceOption.price_per_session ────────────────────────────────────────

@pytest.mark.django_db
def test_price_per_session_single():
    """1 процедура: цена за сеанс == полная цена."""
    opt = baker.make("services_app.ServiceOption", price=Decimal("3000"), units=1, duration_min=60)
    assert opt.price_per_session == Decimal("3000")


@pytest.mark.django_db
def test_price_per_session_multi():
    """5 процедур: цена за сеанс == цена / 5."""
    opt = baker.make("services_app.ServiceOption", price=Decimal("10000"), units=5, duration_min=60)
    assert opt.price_per_session == Decimal("2000")


@pytest.mark.django_db
def test_price_per_session_zero_units():
    """units=0 (на уровне Python, без БД) → None, не ZeroDivisionError."""
    opt = baker.make("services_app.ServiceOption", price=Decimal("3000"), units=1, duration_min=60)
    opt.units = 0
    assert opt.price_per_session is None


# ─── Bundle.total_price ──────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bundle_total_price_fixed():
    """fixed_price перекрывает подсчёт по позициям."""
    bundle = baker.make("services_app.Bundle", fixed_price=Decimal("5000"), discount=Decimal("0"))
    assert bundle.total_price() == Decimal("5000")


@pytest.mark.django_db
def test_bundle_total_price_calculated(bundle_with_items):
    """Цена = сумма позиций (3000 + 1500 = 4500), скидка 0."""
    assert bundle_with_items.total_price() == Decimal("4500")


@pytest.mark.django_db
def test_bundle_total_price_with_discount():
    """Скидка вычитается из суммы: 2000 - 500 = 1500."""
    bundle = baker.make(
        "services_app.Bundle", fixed_price=None, discount=Decimal("500"), is_active=True
    )
    opt = baker.make("services_app.ServiceOption", price=Decimal("2000"), units=1, duration_min=60)
    baker.make("services_app.BundleItem", bundle=bundle, option=opt, quantity=1)
    assert bundle.total_price() == Decimal("1500")


@pytest.mark.django_db
def test_bundle_total_price_discount_exceeds_sum():
    """Скидка больше суммы → результат не отрицательный."""
    bundle = baker.make(
        "services_app.Bundle", fixed_price=None, discount=Decimal("9999"), is_active=True
    )
    opt = baker.make("services_app.ServiceOption", price=Decimal("100"), units=1, duration_min=30)
    baker.make("services_app.BundleItem", bundle=bundle, option=opt, quantity=1)
    assert bundle.total_price() == Decimal("0.00")


@pytest.mark.django_db
def test_bundle_total_price_quantity_multiplied():
    """quantity=2 удваивает цену позиции: 1000 × 2 = 2000."""
    bundle = baker.make("services_app.Bundle", fixed_price=None, discount=Decimal("0"))
    opt = baker.make("services_app.ServiceOption", price=Decimal("1000"), units=1, duration_min=30)
    baker.make("services_app.BundleItem", bundle=bundle, option=opt, quantity=2)
    assert bundle.total_price() == Decimal("2000")


# ─── Bundle.total_duration_min ───────────────────────────────────────────────

@pytest.mark.django_db
def test_bundle_total_duration_simple_sum(bundle_with_items):
    """60 + 30 = 90 мин."""
    assert bundle_with_items.total_duration_min() == 90


@pytest.mark.django_db
def test_bundle_total_duration_with_quantity():
    """quantity=3: 45 × 3 = 135 мин."""
    bundle = baker.make("services_app.Bundle", fixed_price=None, discount=Decimal("0"))
    opt = baker.make("services_app.ServiceOption", price=Decimal("1000"), units=1, duration_min=45)
    baker.make("services_app.BundleItem", bundle=bundle, option=opt, quantity=3)
    assert bundle.total_duration_min() == 135


@pytest.mark.django_db
def test_bundle_total_duration_empty():
    """Пустой комплекс → 0 минут."""
    bundle = baker.make("services_app.Bundle", fixed_price=None, discount=Decimal("0"))
    assert bundle.total_duration_min() == 0


# ─── Review.get_initial_letter ───────────────────────────────────────────────

@pytest.mark.django_db
def test_review_initial_letter_normal():
    r = baker.make("services_app.Review", author_name="Мария", date=datetime.date.today())
    assert r.get_initial_letter() == "М"


@pytest.mark.django_db
def test_review_initial_letter_latin():
    r = baker.make("services_app.Review", author_name="anna", date=datetime.date.today())
    assert r.get_initial_letter() == "A"


@pytest.mark.django_db
def test_review_initial_letter_empty():
    """Пустое имя → '?'."""
    r = baker.make("services_app.Review", author_name="", date=datetime.date.today())
    assert r.get_initial_letter() == "?"


# ─── Master.__str__ ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_master_str():
    master = baker.make("services_app.Master", name="Ольга Иванова")
    assert str(master) == "Ольга Иванова"
