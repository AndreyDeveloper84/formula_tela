"""Тесты custom QuerySet менеджеров (services_app + agents)."""
import pytest
from decimal import Decimal
from model_bakery import baker

from services_app.models import (
    Bundle, Master, Promotion, Review, Service, ServiceCategory, ServiceOption,
)
from agents.models import LandingPage


# ── Service ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestServiceQuerySet:
    def test_active_excludes_inactive(self):
        baker.make("services_app.Service", is_active=True, _quantity=2)
        baker.make("services_app.Service", is_active=False)
        assert Service.objects.active().count() == 2

    def test_inactive_returns_only_inactive(self):
        baker.make("services_app.Service", is_active=True)
        baker.make("services_app.Service", is_active=False, _quantity=2)
        assert Service.objects.inactive().count() == 2

    def test_popular_active_chain(self):
        baker.make("services_app.Service", is_active=True, is_popular=True)
        baker.make("services_app.Service", is_active=True, is_popular=False)
        baker.make("services_app.Service", is_active=False, is_popular=True)
        assert Service.objects.active().popular().count() == 1

    def test_with_options_prefetches_only_active(self, django_assert_num_queries):
        svc = baker.make("services_app.Service", is_active=True)
        baker.make("services_app.ServiceOption", service=svc, is_active=True, _quantity=2)
        baker.make("services_app.ServiceOption", service=svc, is_active=False)
        # 1 query для Service + 1 для prefetch options
        with django_assert_num_queries(2):
            svc_loaded = list(Service.objects.active().with_options())[0]
            assert len(list(svc_loaded.options.all())) == 2

    def test_with_slug_excludes_empty_and_null(self):
        # Service.save() автогенерирует slug из name — обходим через queryset.update()
        services = baker.make("services_app.Service", _quantity=3)
        Service.objects.filter(pk=services[0].pk).update(slug="has-slug")
        Service.objects.filter(pk=services[1].pk).update(slug="")
        Service.objects.filter(pk=services[2].pk).update(slug=None)
        assert Service.objects.with_slug().count() == 1

    def test_with_category_uses_select_related(self, django_assert_num_queries):
        cat = baker.make("services_app.ServiceCategory")
        baker.make("services_app.Service", category=cat, is_active=True, _quantity=3)
        # 1 query вместо 4 (1 services + 3 categories)
        with django_assert_num_queries(1):
            for s in Service.objects.active().with_category():
                _ = s.category.name


# ── ServiceOption ──────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestServiceOptionQuerySet:
    def test_active_excludes_inactive(self):
        svc = baker.make("services_app.Service")
        baker.make("services_app.ServiceOption", service=svc, is_active=True, _quantity=3)
        baker.make("services_app.ServiceOption", service=svc, is_active=False)
        assert ServiceOption.objects.active().count() == 3

    def test_for_service_filters_correctly(self):
        svc1 = baker.make("services_app.Service")
        svc2 = baker.make("services_app.Service")
        baker.make("services_app.ServiceOption", service=svc1, _quantity=2)
        baker.make("services_app.ServiceOption", service=svc2)
        assert ServiceOption.objects.for_service(svc1).count() == 2


# ── ServiceCategory ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestServiceCategoryQuerySet:
    def test_with_active_services_excludes_empty_categories(self):
        cat_with_svc = baker.make("services_app.ServiceCategory")
        baker.make("services_app.ServiceCategory")  # пустая, без активных услуг
        baker.make("services_app.Service", category=cat_with_svc, is_active=True)
        # только первая категория имеет активные услуги
        categories = list(ServiceCategory.objects.with_active_services())
        assert len(categories) == 1
        assert categories[0].pk == cat_with_svc.pk

    def test_with_active_services_distinct_for_multiple_services(self):
        # 2 активные услуги в одной категории → категория возвращается один раз (.distinct())
        cat = baker.make("services_app.ServiceCategory")
        baker.make("services_app.Service", category=cat, is_active=True, _quantity=2)
        assert ServiceCategory.objects.with_active_services().count() == 1

    def test_with_active_services_ignores_inactive(self):
        cat = baker.make("services_app.ServiceCategory")
        baker.make("services_app.Service", category=cat, is_active=False)
        assert ServiceCategory.objects.with_active_services().count() == 0

    def test_by_slug(self):
        baker.make("services_app.ServiceCategory", slug="massazh")
        baker.make("services_app.ServiceCategory", slug="epilyatsiya")
        assert ServiceCategory.objects.by_slug("massazh").count() == 1


# ── Master ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestMasterQuerySet:
    def test_active_excludes_inactive(self):
        baker.make("services_app.Master", is_active=True, _quantity=2)
        baker.make("services_app.Master", is_active=False)
        assert Master.objects.active().count() == 2

    def test_with_services_prefetches(self, django_assert_num_queries):
        master = baker.make("services_app.Master", is_active=True)
        services = baker.make("services_app.Service", _quantity=3)
        master.services.set(services)
        # 1 masters + 1 services prefetch
        with django_assert_num_queries(2):
            m_loaded = list(Master.objects.active().with_services())[0]
            assert len(list(m_loaded.services.all())) == 3

    def test_with_services_and_options_prefetches_deep(self, django_assert_num_queries):
        master = baker.make("services_app.Master", is_active=True)
        svc = baker.make("services_app.Service")
        baker.make("services_app.ServiceOption", service=svc, _quantity=2)
        master.services.add(svc)
        # 1 master + 1 services + 1 options
        with django_assert_num_queries(3):
            m_loaded = list(Master.objects.active().with_services_and_options())[0]
            for s in m_loaded.services.all():
                _ = list(s.options.all())


# ── Bundle ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBundleQuerySet:
    def test_active_popular_chain(self):
        baker.make("services_app.Bundle", is_active=True, is_popular=True)
        baker.make("services_app.Bundle", is_active=True, is_popular=False)
        baker.make("services_app.Bundle", is_active=False, is_popular=True)
        assert Bundle.objects.active().popular().count() == 1

    def test_with_items_prefetches(self, django_assert_num_queries):
        bundle = baker.make("services_app.Bundle", is_active=True)
        svc = baker.make("services_app.Service")
        opt = baker.make("services_app.ServiceOption", service=svc)
        baker.make("services_app.BundleItem", bundle=bundle, option=opt, _quantity=2)
        # 1 bundle + 1 items + 1 option + 1 service
        with django_assert_num_queries(4):
            b_loaded = list(Bundle.objects.active().with_items())[0]
            for item in b_loaded.items.all():
                _ = item.option.service.name

    def test_with_slug_excludes_empty(self):
        baker.make("services_app.Bundle", slug="combo")
        baker.make("services_app.Bundle", slug="")
        baker.make("services_app.Bundle", slug=None)
        assert Bundle.objects.with_slug().count() == 1


# ── Promotion ──────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestPromotionQuerySet:
    def test_active_excludes_inactive(self):
        baker.make("services_app.Promotion", is_active=True, _quantity=2)
        baker.make("services_app.Promotion", is_active=False)
        assert Promotion.objects.active().count() == 2

    def test_with_options_prefetches(self, django_assert_num_queries):
        promo = baker.make("services_app.Promotion", is_active=True)
        svc = baker.make("services_app.Service")
        opts = baker.make("services_app.ServiceOption", service=svc, _quantity=2)
        promo.options.set(opts)
        # 1 promo + 1 options + 1 service (для options__service)
        with django_assert_num_queries(3):
            p_loaded = list(Promotion.objects.active().with_options())[0]
            for opt in p_loaded.options.all():
                _ = opt.service.name


# ── Review ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestReviewQuerySet:
    def test_active_excludes_inactive(self):
        import datetime
        baker.make("services_app.Review", is_active=True, date=datetime.date.today(), _quantity=2)
        baker.make("services_app.Review", is_active=False, date=datetime.date.today())
        assert Review.objects.active().count() == 2


# ── LandingPage ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLandingPageQuerySet:
    def test_published_returns_only_published(self):
        baker.make("agents.LandingPage", status=LandingPage.STATUS_PUBLISHED, _quantity=2)
        baker.make("agents.LandingPage", status=LandingPage.STATUS_DRAFT)
        baker.make("agents.LandingPage", status=LandingPage.STATUS_REJECTED)
        assert LandingPage.objects.published().count() == 2

    def test_draft_and_pending_review(self):
        baker.make("agents.LandingPage", status=LandingPage.STATUS_DRAFT, _quantity=2)
        baker.make("agents.LandingPage", status=LandingPage.STATUS_REVIEW)
        assert LandingPage.objects.draft().count() == 2
        assert LandingPage.objects.pending_review().count() == 1

    def test_needs_qc_returns_draft_and_review_not_published(self):
        baker.make("agents.LandingPage", status=LandingPage.STATUS_DRAFT)
        baker.make("agents.LandingPage", status=LandingPage.STATUS_REVIEW)
        baker.make("agents.LandingPage", status=LandingPage.STATUS_PUBLISHED)
        baker.make("agents.LandingPage", status=LandingPage.STATUS_REJECTED)
        qs = LandingPage.objects.needs_qc()
        assert qs.count() == 2
        statuses = set(qs.values_list("status", flat=True))
        assert statuses == {LandingPage.STATUS_DRAFT, LandingPage.STATUS_REVIEW}

    def test_by_cluster(self):
        from agents.models import SeoKeywordCluster
        cluster = baker.make("agents.SeoKeywordCluster")
        baker.make("agents.LandingPage", cluster=cluster, _quantity=2)
        baker.make("agents.LandingPage", cluster=None)
        assert LandingPage.objects.by_cluster(cluster).count() == 2

    def test_by_slug(self):
        baker.make("agents.LandingPage", slug="massazh-spiny")
        baker.make("agents.LandingPage", slug="epilyatsiya")
        assert LandingPage.objects.by_slug("massazh-spiny").count() == 1


# ── Composability (один сценарий на модель, где нетривиально) ─────────────

@pytest.mark.django_db
class TestComposability:
    def test_service_chain_active_popular_with_options(self):
        svc = baker.make("services_app.Service", is_active=True, is_popular=True)
        baker.make("services_app.Service", is_active=True, is_popular=False)
        baker.make("services_app.ServiceOption", service=svc, is_active=True)
        qs = Service.objects.active().popular().with_options().with_category()
        assert qs.count() == 1

    def test_landing_chain_by_cluster_draft(self):
        from agents.models import SeoKeywordCluster
        cluster = baker.make("agents.SeoKeywordCluster")
        baker.make("agents.LandingPage", cluster=cluster, status=LandingPage.STATUS_DRAFT)
        baker.make("agents.LandingPage", cluster=cluster, status=LandingPage.STATUS_PUBLISHED)
        assert LandingPage.objects.by_cluster(cluster).draft().count() == 1
