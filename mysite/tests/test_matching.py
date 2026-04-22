"""Юнит-тесты fuzzy-matching для SEO-кластеризации."""
import pytest

from agents._matching import cluster_match, tokens


class TestTokens:
    def test_lemmatizes_inflections(self):
        t = tokens("массажа спины")
        assert "массаж" in t
        assert "спина" in t

    def test_removes_stop_words(self):
        t = tokens("массаж в пензе")
        assert "в" not in t
        assert "массаж" in t
        assert "пенза" in t

    def test_lowercases(self):
        t = tokens("Массаж ПЕНЗА")
        assert t == tokens("массаж пенза")

    def test_filters_short_tokens(self):
        t = tokens("с о й массаж")
        assert t == frozenset({"массаж"})

    def test_empty_phrase(self):
        assert tokens("") == frozenset()


class TestClusterMatch:
    @pytest.mark.parametrize("kw,query,expected", [
        # 2-токенный keyword: нужны оба
        ("массаж пенза", "пенза массаж пнз", True),
        ("массаж пенза", "формула тела пенза", False),
        ("массаж пенза", "массажа в пензе", True),
        # 3-токенный keyword: 50%+ (округление до 2/3)
        ("лазерная эпиляция бикини", "тотальное бикини в пензе", False),  # 1/3 = 33%
        ("лазерная эпиляция бикини", "лазерная эпиляция бикини пенза", True),  # 3/3
        ("массаж при остеохондрозе позвоночника", "массаж остеохондроз", True),  # 2/3
        # Падежи
        ("массаж спины", "массажа спине", True),
        ("антицеллюлитный массаж ягодиц", "антицеллюлитный массаж", True),  # 2/3 = 67%
    ])
    def test_cases(self, kw, query, expected):
        assert cluster_match(tokens(kw), tokens(query)) == expected

    def test_empty_keyword_does_not_match(self):
        assert cluster_match(frozenset(), tokens("массаж")) is False

    def test_long_keyword_threshold_50_percent(self):
        # 4-токенный keyword: 2/4 = 50% → match
        kw = tokens("классический массаж спины расслабляющий")
        q = tokens("массаж классический пенза")  # пересечение: массаж, классический = 2/4
        assert cluster_match(kw, q) is True
