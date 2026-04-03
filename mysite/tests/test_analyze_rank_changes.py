"""
Тесты для задачи 3.2: analyze_rank_changes и send_seo_alert.
Все Telegram-вызовы замоканы. БД через pytest-django.
"""
import datetime
import pytest
from unittest.mock import MagicMock, patch, call
from model_bakery import baker


# ── Фикстуры ─────────────────────────────────────────────────────────────────

@pytest.fixture
def cluster(db):
    return baker.make(
        "agents.SeoKeywordCluster",
        name="Массаж спины Пенза",
        target_url="/massazh-spiny",
        is_active=True,
    )


def _make_snapshot(cluster, date, clicks, impressions=0, avg_position=0.0):
    """Хелпер создания снапшота."""
    return baker.make(
        "agents.SeoClusterSnapshot",
        cluster=cluster,
        date=date,
        total_clicks=clicks,
        total_impressions=impressions,
        avg_position=avg_position,
    )


# ── analyze_rank_changes ─────────────────────────────────────────────────────

class TestAnalyzeRankChanges:

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_click_drop_20pct_triggers_alert(self, mock_alert, cluster):
        """Падение кликов ровно 20% -> алерт отправляется."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        _make_snapshot(cluster, week_ago, clicks=100)
        _make_snapshot(cluster, today, clicks=80)   # -20% ровно

        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        mock_alert.assert_called_once()
        alerts = mock_alert.call_args[0][0]
        assert len(alerts) == 1
        assert alerts[0]["type"] == "click_drop"
        assert alerts[0]["change"] == -20.0

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_click_drop_below_20pct_no_alert(self, mock_alert, cluster):
        """Падение кликов 19% -> алерт НЕ отправляется (не достигли порога)."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        _make_snapshot(cluster, week_ago, clicks=100)
        _make_snapshot(cluster, today, clicks=81)   # -19%

        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        mock_alert.assert_not_called()

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_position_drop_3_triggers_alert(self, mock_alert, cluster):
        """Ухудшение позиции ровно на 3 -> алерт отправляется."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        _make_snapshot(cluster, week_ago, clicks=50, avg_position=5.0)
        _make_snapshot(cluster, today, clicks=50, avg_position=8.0)   # +3 мест

        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        mock_alert.assert_called_once()
        alerts = mock_alert.call_args[0][0]
        assert alerts[0]["type"] == "position_drop"
        assert alerts[0]["change"] == 3.0

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_position_drop_below_3_no_alert(self, mock_alert, cluster):
        """Ухудшение позиции на 2.9 -> алерт НЕ отправляется."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        _make_snapshot(cluster, week_ago, clicks=50, avg_position=5.0)
        _make_snapshot(cluster, today, clicks=50, avg_position=7.9)   # +2.9

        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        mock_alert.assert_not_called()

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_alert_format_fields(self, mock_alert, cluster):
        """Алерт содержит все обязательные поля из спецификации."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        _make_snapshot(cluster, week_ago, clicks=100)
        _make_snapshot(cluster, today, clicks=60)   # -40%

        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        alert = mock_alert.call_args[0][0][0]
        assert "cluster" in alert
        assert "type" in alert
        assert "change" in alert
        assert "current" in alert
        assert "previous" in alert
        assert "url" in alert
        assert alert["cluster"] == "Массаж спины Пенза"
        assert alert["url"] == "/massazh-spiny"
        assert alert["previous"] == 100.0
        assert alert["current"] == 60.0

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_no_alert_when_no_snapshots(self, mock_alert, cluster):
        """Нет снапшотов за сегодня -> send_seo_alert не вызывается."""
        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        mock_alert.assert_not_called()

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_no_alert_without_previous_snapshot(self, mock_alert, cluster):
        """Есть только сегодняшний снапшот (нет прошлой недели) -> без алерта."""
        today = datetime.date.today()
        _make_snapshot(cluster, today, clicks=50, avg_position=10.0)

        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        mock_alert.assert_not_called()

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_creates_seotask_on_click_drop(self, mock_alert, cluster):
        """Падение кликов -> SeoTask с priority=high создаётся в БД."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        _make_snapshot(cluster, week_ago, clicks=100)
        _make_snapshot(cluster, today, clicks=60)

        from agents.tasks import analyze_rank_changes
        from agents.models import SeoTask

        analyze_rank_changes()

        task = SeoTask.objects.get(
            task_type=SeoTask.TYPE_UPDATE_META,
            target_url="/massazh-spiny",
        )
        assert task.priority == SeoTask.PRIORITY_HIGH
        assert task.status == SeoTask.STATUS_OPEN

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_creates_seotask_on_position_drop(self, mock_alert, cluster):
        """Просадка позиции -> SeoTask с priority=medium создаётся в БД."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        _make_snapshot(cluster, week_ago, clicks=50, avg_position=5.0)
        _make_snapshot(cluster, today, clicks=50, avg_position=9.0)

        from agents.tasks import analyze_rank_changes
        from agents.models import SeoTask

        analyze_rank_changes()

        task = SeoTask.objects.get(
            task_type=SeoTask.TYPE_UPDATE_META,
            target_url="/massazh-spiny",
        )
        assert task.priority == SeoTask.PRIORITY_MEDIUM

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_no_duplicate_seotask_on_repeat_run(self, mock_alert, cluster):
        """Повторный запуск -> дубль SeoTask не создаётся (get_or_create)."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        _make_snapshot(cluster, week_ago, clicks=100)
        _make_snapshot(cluster, today, clicks=60)

        from agents.tasks import analyze_rank_changes
        from agents.models import SeoTask

        analyze_rank_changes()
        analyze_rank_changes()

        assert SeoTask.objects.filter(target_url="/massazh-spiny").count() == 1

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_both_alert_types_in_one_run(self, mock_alert, db):
        """Один кластер может генерировать оба типа алерта одновременно."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        c = baker.make("agents.SeoKeywordCluster", target_url="/both")
        _make_snapshot(c, week_ago, clicks=100, avg_position=5.0)
        _make_snapshot(c, today, clicks=60, avg_position=10.0)  # -40% и +5 позиций

        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        all_alerts = mock_alert.call_args[0][0]
        types = [a["type"] for a in all_alerts]
        assert "click_drop" in types
        assert "position_drop" in types

    @pytest.mark.django_db
    @patch("agents.telegram.send_seo_alert")
    def test_multiple_clusters_all_checked(self, mock_alert, db):
        """Несколько кластеров — все проверяются, алерты по каждому."""
        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=7)

        for i in range(3):
            c = baker.make(
                "agents.SeoKeywordCluster",
                name=f"Кластер {i}",
                target_url=f"/cluster-{i}",
                is_active=True,
            )
            _make_snapshot(c, week_ago, clicks=100)
            _make_snapshot(c, today, clicks=50)  # -50%

        from agents.tasks import analyze_rank_changes
        analyze_rank_changes()

        all_alerts = mock_alert.call_args[0][0]
        assert len(all_alerts) == 3


# ── send_seo_alert ───────────────────────────────────────────────────────────

class TestSendSeoAlert:

    @patch("agents.telegram.send_telegram")
    def test_click_drop_alert_formatting(self, mock_tg):
        """click_drop алерт -> правильно отформатирован в HTML."""
        mock_tg.return_value = True
        from agents.telegram import send_seo_alert

        alerts = [{
            "cluster": "Массаж спины",
            "type": "click_drop",
            "change": -35.0,
            "current": 65.0,
            "previous": 100.0,
            "url": "/massazh-spiny",
        }]
        send_seo_alert(alerts)

        text = mock_tg.call_args[0][0]
        assert "Массаж спины" in text
        assert "-35.0%" in text
        assert "/massazh-spiny" in text
        assert "Падение кликов" in text

    @patch("agents.telegram.send_telegram")
    def test_position_drop_alert_formatting(self, mock_tg):
        """position_drop алерт -> содержит информацию о позиции."""
        mock_tg.return_value = True
        from agents.telegram import send_seo_alert

        alerts = [{
            "cluster": "Антицеллюлитный массаж",
            "type": "position_drop",
            "change": 5.5,
            "current": 12.5,
            "previous": 7.0,
            "url": "/antitsellyulitnyj",
        }]
        send_seo_alert(alerts)

        text = mock_tg.call_args[0][0]
        assert "Антицеллюлитный массаж" in text
        assert "5.5" in text
        assert "/antitsellyulitnyj" in text
        assert "Ухудшение позиций" in text

    @patch("agents.telegram.send_telegram")
    def test_mixed_alerts_single_message(self, mock_tg):
        """Смешанные алерты -> одно сообщение, send_telegram вызван один раз."""
        mock_tg.return_value = True
        from agents.telegram import send_seo_alert

        alerts = [
            {"cluster": "А", "type": "click_drop",
             "change": -25.0, "current": 75.0, "previous": 100.0, "url": "/a"},
            {"cluster": "Б", "type": "position_drop",
             "change": 4.0, "current": 9.0, "previous": 5.0, "url": "/b"},
        ]
        send_seo_alert(alerts)

        assert mock_tg.call_count == 1  # одно сообщение
        text = mock_tg.call_args[0][0]
        assert "А" in text
        assert "Б" in text

    @patch("agents.telegram.send_telegram")
    def test_empty_alerts_returns_true_no_send(self, mock_tg):
        """Пустой список алертов -> send_telegram НЕ вызывается, возвращает True."""
        from agents.telegram import send_seo_alert

        result = send_seo_alert([])

        assert result is True
        mock_tg.assert_not_called()

    @patch("agents.telegram.send_telegram", return_value=False)
    def test_returns_false_when_telegram_fails(self, mock_tg):
        """Если send_telegram вернул False -> send_seo_alert тоже False."""
        from agents.telegram import send_seo_alert

        alerts = [{
            "cluster": "Тест", "type": "click_drop",
            "change": -25.0, "current": 75.0, "previous": 100.0, "url": "/test",
        }]
        result = send_seo_alert(alerts)

        assert result is False

    @patch("agents.telegram.send_telegram")
    def test_sorted_by_severity(self, mock_tg):
        """click_drop алерты отсортированы — худшее падение вверху."""
        mock_tg.return_value = True
        from agents.telegram import send_seo_alert

        alerts = [
            {"cluster": "Лёгкое", "type": "click_drop",
             "change": -21.0, "current": 79.0, "previous": 100.0, "url": "/light"},
            {"cluster": "Тяжёлое", "type": "click_drop",
             "change": -55.0, "current": 45.0, "previous": 100.0, "url": "/heavy"},
        ]
        send_seo_alert(alerts)

        text = mock_tg.call_args[0][0]
        pos_light = text.find("Лёгкое")
        pos_heavy = text.find("Тяжёлое")
        # Тяжёлое должно быть первым (наиболее отрицательный change)
        assert pos_heavy < pos_light
