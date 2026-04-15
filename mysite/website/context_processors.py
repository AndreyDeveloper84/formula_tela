from django.conf import settings as django_settings

from services_app.models import SiteSettings


def settings(request):
    """Добавляет settings в контекст всех шаблонов"""
    return {
        'settings': SiteSettings.objects.first(),
        'YANDEX_VERIFICATION': getattr(django_settings, 'YANDEX_VERIFICATION', ''),
    }

