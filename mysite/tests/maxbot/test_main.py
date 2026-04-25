"""T-03 RED: main entrypoint — модуль импортируется, dispatcher собирается."""


def test_maxbot_package_importable():
    import maxbot
    assert maxbot is not None


def test_main_module_importable():
    """from maxbot import main — без ImportError."""
    from maxbot import main
    assert hasattr(main, "build_dispatcher")
    assert hasattr(main, "run")


def test_build_dispatcher_returns_dispatcher(monkeypatch):
    """build_dispatcher() возвращает Dispatcher с зарегистрированными router'ами."""
    monkeypatch.setenv("MAX_BOT_TOKEN", "x")
    from maxapi import Dispatcher
    from maxbot.main import build_dispatcher
    dp = build_dispatcher()
    assert isinstance(dp, Dispatcher)


def test_django_bootstrap_idempotent():
    """setup_django() безопасно вызывать многократно."""
    from maxbot.django_bootstrap import setup_django
    setup_django()
    setup_django()  # второй вызов — no-op, не падает
    from django.conf import settings
    assert settings.configured
