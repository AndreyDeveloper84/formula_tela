from django.conf import settings
from openai import OpenAI


def get_openai_client() -> OpenAI:
    """Создаёт OpenAI клиент с поддержкой HTTP-прокси (OPENAI_PROXY)."""
    kwargs = {"api_key": settings.OPENAI_API_KEY}
    if getattr(settings, "OPENAI_BASE_URL", ""):
        kwargs["base_url"] = settings.OPENAI_BASE_URL
    proxy = getattr(settings, "OPENAI_PROXY", "")
    if proxy:
        import httpx
        kwargs["http_client"] = httpx.Client(proxy=proxy)
    return OpenAI(**kwargs)
