"""
Middleware для website.

RatelimitMiddleware: перехватывает django_ratelimit.exceptions.Ratelimited
и возвращает JSON-ответ 429 вместо дефолтного 403 HTML. Это нужно чтобы
booking API отдавал клиенту корректный статус (429 Too Many Requests)
при превышении лимита.
"""
from django.http import JsonResponse
from django_ratelimit.exceptions import Ratelimited


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
