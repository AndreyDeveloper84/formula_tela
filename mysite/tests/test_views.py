"""
Тесты Django-вью: HTTP статусы, контекст шаблонов.
Без реальных вызовов внешних API.
"""
import pytest
from model_bakery import baker


# ─── home ────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_home_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_home_popular_services_in_context(client):
    baker.make("services_app.Service", is_active=True, is_popular=True, _quantity=2)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "top_items" in resp.context


@pytest.mark.django_db
def test_home_no_popular_bundles_section(client):
    """Блок «Популярные комплексы» удалён со страницы — пользователь просил скрыть."""
    baker.make("services_app.Bundle", is_active=True, is_popular=True, _quantity=3)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Популярные комплексы" not in resp.content.decode("utf-8")
    assert "popular_bundles" not in resp.context


@pytest.mark.django_db
def test_home_promo_banner_wires_booking_modal(client, service, service_option):
    """Промо с options → кнопка баннера вызывает openBookingModal(svc_id, ...),
    модалка #bookingModal подключена на странице."""
    from datetime import date, timedelta
    promo = baker.make(
        "services_app.Promotion",
        title="Знакомство с мастером",
        is_active=True,
        starts_at=date.today() - timedelta(days=1),
        ends_at=date.today() + timedelta(days=30),
    )
    promo.options.add(service_option)

    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.context["promo_booking_svc_id"] == service.id
    html = resp.content.decode("utf-8")
    assert f"openBookingModal({service.id}," in html
    assert 'id="bookingModal"' in html
    # flatpickr тянется только если модалка нужна
    assert "flatpickr" in html


@pytest.mark.django_db
def test_home_no_promo_no_booking_modal(client):
    """Нет активных промо → модалка не подключается (экономия flatpickr)."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.context["promo_booking_svc_id"] is None
    html = resp.content.decode("utf-8")
    assert 'id="bookingModal"' not in html


@pytest.mark.django_db
def test_hidden_category_not_listed_on_home_or_services(client):
    """Категория с is_active=False не показывается на главной, в каталоге и sitemap."""
    visible = baker.make("services_app.ServiceCategory", name="Видимая", is_active=True, slug="visible")
    hidden = baker.make("services_app.ServiceCategory", name="Скрытая", is_active=False, slug="hidden")
    baker.make("services_app.Service", category=visible, is_active=True)
    baker.make("services_app.Service", category=hidden, is_active=True)

    r = client.get("/")
    assert r.status_code == 200
    html = r.content.decode("utf-8")
    assert "Видимая" in html
    assert "Скрытая" not in html

    r = client.get("/services/")
    html = r.content.decode("utf-8")
    assert "Видимая" in html
    assert "Скрытая" not in html

    # Прямой заход по slug скрытой категории → 404
    r = client.get(f"/services/{hidden.id}/")
    assert r.status_code == 404


@pytest.mark.django_db
def test_header_shows_phone_icon_if_contact_phone_set(client):
    """Если SiteSettings.contact_phone задан — в header появляется иконка-ссылка tel:"""
    from services_app.models import SiteSettings
    SiteSettings.objects.all().delete()
    baker.make(SiteSettings, contact_phone="8 (8412) 39-34-33")
    resp = client.get("/")
    html = resp.content.decode("utf-8")
    assert "qc-phone" in html
    assert 'href="tel:+78412393433"' in html or 'href="tel:88412393433"' in html


@pytest.mark.django_db
def test_header_shows_msg_popover_if_any_channel_set(client):
    """Если задан хотя бы один мессенджер — появляется иконка «написать» с dropdown."""
    from services_app.models import SiteSettings
    SiteSettings.objects.all().delete()
    baker.make(SiteSettings, contact_telegram="https://t.me/test")
    resp = client.get("/")
    html = resp.content.decode("utf-8")
    assert "qc-msg" in html
    assert "qc-dropdown" in html
    assert "https://t.me/test" in html
    assert "Telegram</a>" in html


@pytest.mark.django_db
def test_header_no_msg_icon_without_channels(client):
    """Если ни одного мессенджера не задано — dropdown не рендерится."""
    from services_app.models import SiteSettings
    SiteSettings.objects.all().delete()
    baker.make(SiteSettings, contact_phone="", contact_whatsapp="", contact_telegram="",
               contact_vk="", contact_max="", contact_manager_url="")
    resp = client.get("/")
    html = resp.content.decode("utf-8")
    assert "qc-msg" not in html


@pytest.mark.django_db
def test_home_promo_price_uses_discount_percent(client, service):
    """Цена на кнопке промо = option.price × (100 - discount%). PDF показывает
    пользователю реальную скидочную цену, а не полную."""
    from datetime import date, timedelta
    from decimal import Decimal
    opt = baker.make(
        "services_app.ServiceOption",
        service=service, price=Decimal("2500"), is_active=True,
        yclients_service_id="22610238",
    )
    promo = baker.make(
        "services_app.Promotion",
        title="Знакомство",
        is_active=True,
        discount_percent=40,
        starts_at=date.today() - timedelta(days=1),
        ends_at=date.today() + timedelta(days=30),
    )
    promo.options.add(opt)

    resp = client.get("/")
    assert resp.context["promo_booking_price"] == 1500  # 2500 × 0.60
    assert resp.context["promo_booking_option_id"] == opt.id
    html = resp.content.decode("utf-8")
    # promoOpts в onclick
    assert f"pinnedOptionId: {opt.id}" in html
    assert "price: 1500" in html
    assert "autoPickDate: false" in html


# ─── services ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_services_returns_200(client):
    resp = client.get("/services/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_services_categories_in_context(client, category):
    resp = client.get("/services/")
    assert resp.status_code == 200
    assert "categories" in resp.context


# ─── service_detail_by_slug ──────────────────────────────────────────────────

@pytest.mark.django_db
def test_service_detail_valid_slug_200(client, service):
    resp = client.get(f"/uslugi/{service.slug}/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_service_detail_invalid_slug_404(client):
    resp = client.get("/uslugi/ne-sushchestvuet/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_service_detail_inactive_slug_404(client, service):
    """Неактивная услуга → 404."""
    service.is_active = False
    service.save()
    resp = client.get(f"/uslugi/{service.slug}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_service_detail_301_redirect_from_id(client, service):
    """GET /service/<id>/ → 301 на /uslugi/<slug>/."""
    resp = client.get(f"/service/{service.id}/")
    assert resp.status_code == 301
    assert f"/uslugi/{service.slug}/" in resp["Location"]


# ─── masters ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_masters_returns_200(client):
    resp = client.get("/masters/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_masters_only_active_in_context(client):
    baker.make("services_app.Master", is_active=True, _quantity=2)
    baker.make("services_app.Master", is_active=False, _quantity=1)
    resp = client.get("/masters/")
    assert resp.status_code == 200
    masters = resp.context["masters"]
    assert all(m.is_active for m in masters)


# ─── promotions ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_promotions_returns_200(client):
    resp = client.get("/promotions/")
    assert resp.status_code == 200


# ─── bundles ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_bundles_returns_200(client):
    resp = client.get("/bundles/")
    assert resp.status_code == 200


# ─── category_services ───────────────────────────────────────────────────────

@pytest.mark.django_db
def test_category_services_valid_200(client, category):
    # ЧПУ-URL — основной
    resp = client.get(f"/kategorii/{category.slug}/")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_category_services_id_redirects_to_slug(client, category):
    # Legacy /services/<id>/ → 301 на /kategorii/<slug>/
    resp = client.get(f"/services/{category.id}/")
    assert resp.status_code == 301
    assert resp["Location"] == f"/kategorii/{category.slug}/"


@pytest.mark.django_db
def test_category_services_invalid_404(client):
    resp = client.get("/services/99999/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_category_services_context_has_category(client, category):
    resp = client.get(f"/kategorii/{category.slug}/")
    assert resp.context["category"].id == category.id
