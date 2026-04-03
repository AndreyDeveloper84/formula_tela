"""
Тесты для задачи 3.3: notify_new_landing и send_weekly_seo_report.
Все Telegram-вызовы замоканы. БД не требуется.
"""
from unittest.mock import MagicMock, patch


# ── Хелперы ──────────────────────────────────────────────────────────────────

def _make_landing(pk=1, slug="massazh-spiny", h1="Массаж спины в Пензе",
                  cluster_name="Массаж спины"):
    """Создаёт MagicMock, имитирующий LandingPage (duck typing)."""
    landing = MagicMock()
    landing.pk = pk
    landing.slug = slug
    landing.h1 = h1
    landing.cluster = MagicMock()
    landing.cluster.name = cluster_name
    return landing


def _full_report():
    """Полный отчёт со всеми полями для тестов."""
    return {
        "period": "17.02 – 23.02.2026",
        "total_clusters": 13,
        "total_clicks": 542,
        "total_impressions": 12850,
        "avg_position": 8.3,
        "top_growth": [
            {"cluster": "Массаж спины", "change": 35.0, "url": "/massazh-spiny"},
            {"cluster": "LPG массаж", "change": 22.0, "url": "/lpg-massazh"},
        ],
        "top_drops": [
            {"cluster": "Антицеллюлитный", "change": -28.0, "url": "/antitsellyulitnyj"},
        ],
        "opportunities": [
            "Создать страницу для кластера «Лимфодренаж»",
            "Обновить мета-теги на /massazh-lica",
        ],
        "weekly_plan": [
            "Опубликовать лендинг /lpg-massazh",
            "Добавить FAQ на /massazh-spiny",
        ],
    }


# ── notify_new_landing ────────────────────────────────────────────────────────

class TestNotifyNewLanding:

    @patch("agents.telegram.reverse", return_value="/admin/agents/landingpage/1/change/")
    @patch("agents.telegram.send_telegram")
    def test_basic_message_content(self, mock_tg, mock_reverse):
        """Сообщение содержит H1, slug и слово 'модерацию'."""
        mock_tg.return_value = True
        from agents.telegram import notify_new_landing

        landing = _make_landing()
        notify_new_landing(landing)

        text = mock_tg.call_args[0][0]
        assert "Массаж спины в Пензе" in text       # H1
        assert "massazh-spiny" in text                # slug
        assert "модерацию" in text.lower() or "модерацию" in text

    @patch("agents.telegram.reverse", return_value="/admin/agents/landingpage/1/change/")
    @patch("agents.telegram.send_telegram")
    def test_cluster_name_in_message(self, mock_tg, mock_reverse):
        """Название кластера присутствует в сообщении."""
        mock_tg.return_value = True
        from agents.telegram import notify_new_landing

        landing = _make_landing(cluster_name="LPG массаж")
        notify_new_landing(landing)

        text = mock_tg.call_args[0][0]
        assert "LPG массаж" in text

    @patch("agents.telegram.reverse", return_value="/admin/agents/landingpage/1/change/")
    @patch("agents.telegram.send_telegram")
    def test_no_cluster_graceful(self, mock_tg, mock_reverse):
        """landing.cluster = None -> не падает, кластер не упоминается."""
        mock_tg.return_value = True
        from agents.telegram import notify_new_landing

        landing = _make_landing()
        landing.cluster = None
        result = notify_new_landing(landing)

        assert result is True
        text = mock_tg.call_args[0][0]
        assert "Кластер:" not in text

    @patch("agents.telegram.reverse", return_value="/admin/agents/landingpage/1/change/")
    @patch("agents.telegram.send_telegram")
    def test_admin_url_with_site_base_url(self, mock_tg, mock_reverse):
        """SITE_BASE_URL настроен -> полный URL в сообщении."""
        mock_tg.return_value = True
        from agents.telegram import notify_new_landing

        landing = _make_landing()
        with patch("agents.telegram.settings") as mock_settings:
            mock_settings.SITE_BASE_URL = "https://formulatela.ru"
            # Убедимся что getattr работает правильно для SITE_BASE_URL
            notify_new_landing(landing)

        text = mock_tg.call_args[0][0]
        assert "https://formulatela.ru/admin/agents/landingpage/1/change/" in text

    @patch("agents.telegram.reverse", return_value="/admin/agents/landingpage/1/change/")
    @patch("agents.telegram.send_telegram")
    def test_admin_url_without_site_base_url(self, mock_tg, mock_reverse):
        """SITE_BASE_URL не настроен -> относительный путь /admin/..."""
        mock_tg.return_value = True
        from agents.telegram import notify_new_landing

        landing = _make_landing()
        with patch("agents.telegram.settings") as mock_settings:
            # Симулируем отсутствие SITE_BASE_URL
            del mock_settings.SITE_BASE_URL
            type(mock_settings).SITE_BASE_URL = property(
                lambda self: (_ for _ in ()).throw(AttributeError)
            )
            notify_new_landing(landing)

        text = mock_tg.call_args[0][0]
        assert "/admin/agents/landingpage/" in text

    @patch("agents.telegram.reverse", return_value="/admin/agents/landingpage/1/change/")
    @patch("agents.telegram.send_telegram", return_value=False)
    def test_returns_false_when_telegram_fails(self, mock_tg, mock_reverse):
        """send_telegram вернул False -> notify_new_landing тоже False."""
        from agents.telegram import notify_new_landing

        landing = _make_landing()
        result = notify_new_landing(landing)
        assert result is False

    @patch("agents.telegram.reverse", return_value="/admin/agents/landingpage/1/change/")
    @patch("agents.telegram.send_telegram")
    def test_checklist_in_message(self, mock_tg, mock_reverse):
        """Чеклист модерации содержит Title, Description, H1."""
        mock_tg.return_value = True
        from agents.telegram import notify_new_landing

        landing = _make_landing()
        notify_new_landing(landing)

        text = mock_tg.call_args[0][0]
        assert "Title" in text
        assert "Description" in text
        assert "H1" in text

    @patch("agents.telegram.reverse", return_value="/admin/agents/landingpage/1/change/")
    @patch("agents.telegram.send_telegram")
    def test_html_tags_present(self, mock_tg, mock_reverse):
        """Сообщение содержит HTML-теги <b> и <code>."""
        mock_tg.return_value = True
        from agents.telegram import notify_new_landing

        landing = _make_landing()
        notify_new_landing(landing)

        text = mock_tg.call_args[0][0]
        assert "<b>" in text
        assert "<code>" in text


# ── send_weekly_seo_report ────────────────────────────────────────────────────

class TestSendWeeklySeoReport:

    @patch("agents.telegram.send_telegram")
    def test_empty_report_returns_true_no_send(self, mock_tg):
        """Пустой словарь -> True, send_telegram НЕ вызывается."""
        from agents.telegram import send_weekly_seo_report

        result = send_weekly_seo_report({})
        assert result is True
        mock_tg.assert_not_called()

    @patch("agents.telegram.send_telegram")
    def test_period_in_message(self, mock_tg):
        """Период отображается в сообщении."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        send_weekly_seo_report(_full_report())

        text = mock_tg.call_args[0][0]
        assert "17.02 – 23.02.2026" in text

    @patch("agents.telegram.send_telegram")
    def test_total_metrics_displayed(self, mock_tg):
        """Клики и показы отображаются в метриках."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        send_weekly_seo_report(_full_report())

        text = mock_tg.call_args[0][0]
        assert "542" in text       # total_clicks
        assert "12850" in text     # total_impressions

    @patch("agents.telegram.send_telegram")
    def test_avg_position_displayed(self, mock_tg):
        """Средняя позиция отображается."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        send_weekly_seo_report(_full_report())

        text = mock_tg.call_args[0][0]
        assert "8.3" in text

    @patch("agents.telegram.send_telegram")
    def test_top_growth_section(self, mock_tg):
        """Секция лидеров роста содержит кластеры."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        send_weekly_seo_report(_full_report())

        text = mock_tg.call_args[0][0]
        assert "Массаж спины" in text
        assert "LPG массаж" in text
        assert "Лидеры роста" in text

    @patch("agents.telegram.send_telegram")
    def test_top_drops_section(self, mock_tg):
        """Секция просадок содержит кластеры."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        send_weekly_seo_report(_full_report())

        text = mock_tg.call_args[0][0]
        assert "Антицеллюлитный" in text
        assert "Просадки" in text

    @patch("agents.telegram.send_telegram")
    def test_opportunities_section(self, mock_tg):
        """Секция возможностей содержит рекомендации."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        send_weekly_seo_report(_full_report())

        text = mock_tg.call_args[0][0]
        assert "Возможности" in text
        assert "Лимфодренаж" in text

    @patch("agents.telegram.send_telegram")
    def test_weekly_plan_section(self, mock_tg):
        """Секция плана на неделю содержит задачи."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        send_weekly_seo_report(_full_report())

        text = mock_tg.call_args[0][0]
        assert "План на неделю" in text
        assert "lpg-massazh" in text

    @patch("agents.telegram.send_telegram")
    def test_missing_optional_fields(self, mock_tg):
        """Report с минимумом полей (только period) -> не падает."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        result = send_weekly_seo_report({"period": "24.02 – 28.02.2026"})

        assert result is True
        text = mock_tg.call_args[0][0]
        assert "24.02 – 28.02.2026" in text
        # Опциональные секции не отображаются
        assert "Лидеры роста" not in text
        assert "Просадки" not in text
        assert "Возможности" not in text
        assert "План на неделю" not in text

    @patch("agents.telegram.send_telegram", return_value=False)
    def test_returns_false_when_telegram_fails(self, mock_tg):
        """send_telegram вернул False -> send_weekly_seo_report тоже False."""
        from agents.telegram import send_weekly_seo_report

        result = send_weekly_seo_report(_full_report())
        assert result is False

    @patch("agents.telegram.send_telegram")
    def test_single_message_sent(self, mock_tg):
        """Один вызов send_telegram (одно сообщение)."""
        mock_tg.return_value = True
        from agents.telegram import send_weekly_seo_report

        send_weekly_seo_report(_full_report())

        assert mock_tg.call_count == 1
