from django.apps import AppConfig


class ServicesAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'services_app'
    verbose_name = "Сайт салона"

    def ready(self):
        import services_app.signals


