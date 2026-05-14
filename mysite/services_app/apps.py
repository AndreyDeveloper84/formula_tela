from django.apps import AppConfig


class ServicesAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'services_app'
    verbose_name = "Сайт салона"

    def ready(self):
        import services_app.signals
        # Sprint 8 / DRF-726 — bind catalog delta-push webhook receivers.
        # Module-level @receiver decorators take effect on import.
        import services_app.api.v1.catalog.webhooks.signals  # noqa: F401


