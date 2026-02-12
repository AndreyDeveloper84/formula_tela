from services_app.models import SiteSettings


def settings(request):
    """Добавляет settings в контекст всех шаблонов"""
    return {
        'settings': SiteSettings.objects.first()
    }

