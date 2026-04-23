"""
Middleware для website.

RatelimitMiddleware: перехватывает django_ratelimit.exceptions.Ratelimited
и возвращает JSON-ответ 429 вместо дефолтного 403 HTML.

AdminMissingMediaMiddleware: ловит FileNotFoundError в admin-views вместо
500-crash. Типичный случай: ServiceMedia.video_file ссылается на файл,
которого нет в локальной media/ (на проде он есть, свежая dev-машина —
нет). Django при рендере change_view вызывает .size/.url на FileField → OSError.
"""
import logging
from django.contrib import messages
from django.http import JsonResponse, HttpResponseRedirect
from django_ratelimit.exceptions import Ratelimited


logger = logging.getLogger(__name__)


class RatelimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, Ratelimited):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Слишком много запросов. Попробуйте через минуту.",
                },
                status=429,
            )
        return None


class AdminMissingMediaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, (FileNotFoundError, OSError)):
            return None
        if not request.path.startswith("/admin/"):
            return None
        filename = getattr(exception, "filename", None) or str(exception)
        logger.warning(
            "Missing media file in admin: %s (path=%s)", filename, request.path
        )
        messages.error(
            request,
            f"Файл не найден на диске: {filename}. "
            "Локальная media/ не синхронизирована с продом. "
            "Либо загрузите файл, либо очистите поле в БД.",
            fail_silently=True,
        )
        referer = request.META.get("HTTP_REFERER")
        if referer and "/change/" not in referer and "/add/" not in referer:
            return HttpResponseRedirect(referer)
        # /admin/app/model/<id>/change/ → /admin/app/model/
        parts = request.path.strip("/").split("/")
        if len(parts) >= 3 and parts[0] == "admin":
            return HttpResponseRedirect("/" + "/".join(parts[:3]) + "/")
        return HttpResponseRedirect("/admin/")
