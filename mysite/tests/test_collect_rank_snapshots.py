"""Тесты для collect_rank_snapshots с fuzzy matching + записью SeoRankSnapshot."""
import datetime
from unittest.mock import MagicMock, patch

import pytest
from model_bakery import baker


# Stub Webmaster responses
QUERY_STATS = [
    # clicks, impressions, ctr, avg_position
    {"query": "тотальное бикини в пензе", "clicks": 2, "impressions": 3, "ctr": 0.67, "avg_position": 5.0},
    {"query": "массажа спины в пензе", "clicks": 5, "impressions": 10, "ctr": 0.5, "avg_position": 4.0},
    {"query": "формула тела пенза", "clicks": 1, "impressions": 2, "ctr": 0.5, "avg_position": 3.0},
]
PAGE_STATS = [
    {"url": "/massazh-spiny/", "clicks": 5, "impressions": 10, "ctr": 0.5, "avg_position": 4.0},
    {"url": "/", "clicks": 1, "impressions": 2, "ctr": 0.5, "avg_position": 3.0},
]


@pytest.fixture
def patched_wm():
    """Мок Webmaster клиента с fixed responses."""
    with patch("agents.tasks.analyze_rank_changes.delay"):
        with patch("agents.integrations.yandex_webmaster.YandexWebmasterClient.from_settings") as m:
            client = MagicMock()
            client.get_query_stats.return_value = QUERY_STATS
            client.get_top_pages.return_value = PAGE_STATS
            m.return_value = client
            yield client


@pytest.mark.django_db
class TestRawDump:
    def test_query_level_snapshots_created(self, patched_wm):
        from agents.models import SeoRankSnapshot
        from agents.tasks import collect_rank_snapshots

        collect_rank_snapshots()

        qs = SeoRankSnapshot.objects.filter(query__gt="")
        assert qs.count() == len(QUERY_STATS)
        one = qs.get(query="массажа спины в пензе")
        assert one.clicks == 5 and one.impressions == 10

    def test_page_level_snapshots_created(self, patched_wm):
        from agents.models import SeoRankSnapshot
        from agents.tasks import collect_rank_snapshots

        collect_rank_snapshots()

        qs = SeoRankSnapshot.objects.filter(page_url__gt="")
        assert qs.count() == len(PAGE_STATS)
        one = qs.get(page_url="/massazh-spiny/")
        assert one.clicks == 5

    def test_idempotent_double_run(self, patched_wm):
        from agents.models import SeoRankSnapshot
        from agents.tasks import collect_rank_snapshots

        collect_rank_snapshots()
        first = SeoRankSnapshot.objects.count()
        collect_rank_snapshots()
        assert SeoRankSnapshot.objects.count() == first

    def test_empty_webmaster_no_crash(self, patched_wm):
        from agents.tasks import collect_rank_snapshots
        patched_wm.get_query_stats.return_value = []
        patched_wm.get_top_pages.return_value = []

        collect_rank_snapshots()  # не должно падать


@pytest.mark.django_db
class TestFuzzyClusterMatching:
    def test_cluster_matches_inflected_query(self, patched_wm):
        """«массаж спины» матчит «массажа спины в пензе» через лемматизацию."""
        from agents.models import SeoClusterSnapshot
        from agents.tasks import collect_rank_snapshots

        cluster = baker.make(
            "agents.SeoKeywordCluster",
            name="Массаж спины",
            keywords=["массаж спины"],
            is_active=True,
        )
        collect_rank_snapshots()

        snap = SeoClusterSnapshot.objects.get(cluster=cluster, date=datetime.date.today())
        assert snap.matched_queries == 1
        assert snap.total_clicks == 5

    def test_cluster_no_match_unrelated_queries(self, patched_wm):
        """Кластер про чистку лица не должен цеплять массажи."""
        from agents.models import SeoClusterSnapshot
        from agents.tasks import collect_rank_snapshots

        cluster = baker.make(
            "agents.SeoKeywordCluster",
            name="Чистка лица",
            keywords=["чистка лица", "ультразвуковая чистка"],
            is_active=True,
        )
        collect_rank_snapshots()

        snap = SeoClusterSnapshot.objects.get(cluster=cluster, date=datetime.date.today())
        assert snap.matched_queries == 0

    def test_no_duplicate_match_across_keywords(self, patched_wm):
        """Один query не должен засчитываться дважды если совпал с 2 keywords."""
        from agents.models import SeoClusterSnapshot
        from agents.tasks import collect_rank_snapshots

        cluster = baker.make(
            "agents.SeoKeywordCluster",
            name="Массаж",
            keywords=["массаж спины", "массаж спины расслабляющий"],
            is_active=True,
        )
        collect_rank_snapshots()

        snap = SeoClusterSnapshot.objects.get(cluster=cluster, date=datetime.date.today())
        # "массажа спины в пензе" совпадает с обоими keywords, но считается 1 раз
        assert snap.matched_queries == 1
        assert snap.total_clicks == 5
