"""Celery tasks для services_app — conversation lifecycle + learning analytics.

Beat schedule в settings/base.py::CELERY_BEAT_SCHEDULE.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from notifications import send_notification_telegram
from services_app.models import Conversation, FewShotExample, Message


logger = logging.getLogger("services_app.tasks")

STALE_DAYS = 7
ANALYSIS_SAMPLE = 20   # сколько failed conversations брать на анализ
ANALYSIS_MODEL = "gpt-4o-mini"

# Phase 2.4 «Auto-tune #1» constants
FEWSHOT_LOOKBACK_DAYS = 14   # окно для поиска свежих success-диалогов
FEWSHOT_KEEP_ACTIVE = 10     # сколько примеров держим активными в prompt'е
FEWSHOT_MIN_USER_LEN = 6     # игнорим «ок», «да», «угу»
FEWSHOT_MIN_ASSISTANT_LEN = 20


# ─── Phase 1: close stale ─────────────────────────────────────────────────


@shared_task(name="services_app.tasks.close_stale_conversations", bind=True, max_retries=1)
def close_stale_conversations(self):
    """Закрыть активные conversations без активности > STALE_DAYS дней.

    Phase 1 Learning Roadmap. Запускается daily в 03:00 (см. CELERY_BEAT_SCHEDULE).

    Логика:
    - is_active=True AND last_message_at < (now - 7 days)
    - is_active=True AND last_message_at IS NULL AND created_at < (now - 7 days)
      (защита от conversations без сообщений)
    - → outcome=abandoned, is_active=False

    Idempotent — повторный запуск ничего не сломает (фильтр is_active=True).
    """
    cutoff = timezone.now() - timedelta(days=STALE_DAYS)

    stale_qs = Conversation.objects.filter(is_active=True).filter(
        Q(last_message_at__lt=cutoff)
        | Q(last_message_at__isnull=True, created_at__lt=cutoff)
    )

    count = stale_qs.update(
        is_active=False,
        outcome=Conversation.Outcome.ABANDONED.value,
    )
    logger.info(
        "close_stale_conversations: closed %d conversations as abandoned (>%d days inactive)",
        count, STALE_DAYS,
    )
    return {"closed": count, "stale_days": STALE_DAYS}


# ─── Phase 2: LLM meta-analysis of failed conversations ──────────────────


def _serialize_conversation(conv: Conversation, messages: list[Message]) -> str:
    """Форматирует диалог для LLM-промпта."""
    lines = [f"[CONVERSATION id={conv.id} outcome={conv.outcome}]"]
    for m in messages:
        if m.role not in ("user", "assistant"):
            continue
        prefix = "Клиент" if m.role == "user" else "Бот"
        content = (m.content or "").strip()
        if not content and m.action_type:
            content = f"[{m.action_type}]"
        if content:
            lines.append(f"  {prefix}: {content[:200]}")
    return "\n".join(lines)


def _build_analysis_prompt(conv_texts: list[str], sample_count: int) -> list[dict]:
    system = (
        "Ты аналитик чат-бота салона массажа. "
        "Анализируй только предоставленные диалоги — не придумывай ситуации. "
        "Ответь строго JSON без markdown-блоков:\n"
        '{"patterns": [...], "weak_intents": [...], "prompt_additions": [...], "summary": "..."}'
    )
    conversations_block = "\n\n".join(conv_texts)
    user_content = (
        f"Ниже {sample_count} неудавшихся диалогов (исход: abandoned/redirected/error).\n\n"
        f"{conversations_block}\n\n"
        "Проанализируй и верни JSON:\n"
        "- patterns: список строк — что пошло не так (кратко, до 5 паттернов)\n"
        "- weak_intents: намерения клиентов, которые бот плохо обрабатывает (до 5)\n"
        "- prompt_additions: конкретные фразы/правила для добавления в system-prompt бота (до 5)\n"
        "- summary: 1-2 предложения общего вывода"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def _get_sync_openai_client():
    """Sync OpenAI client с прокси (аналог agents/agents/__init__.py::get_openai_client)."""
    from openai import OpenAI
    proxy = os.getenv("OPENAI_PROXY") or ""
    kwargs: dict = {}
    if proxy:
        import httpx
        kwargs["http_client"] = httpx.Client(proxy=proxy)
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY", ""), **kwargs)


def _run_llm_analysis(conv_texts: list[str], sample_count: int, openai_client=None) -> dict:
    """Вызывает LLM и возвращает распарсенный dict."""
    if openai_client is None:
        openai_client = _get_sync_openai_client()

    messages = _build_analysis_prompt(conv_texts, sample_count)
    completion = openai_client.chat.completions.create(
        model=ANALYSIS_MODEL,
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    raw = completion.choices[0].message.content or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("analyze_failed_conversations: LLM returned non-JSON: %r", raw[:200])
        return {"patterns": [], "weak_intents": [], "prompt_additions": [], "summary": raw[:300]}


def _format_telegram_report(result: dict, sample_count: int) -> str:
    def _bullets(items: list) -> str:
        return "\n".join(f"  • {item}" for item in (items or [])) or "  —"

    return (
        f"🤖📊 Learning Report — анализ {sample_count} неудавшихся диалогов\n\n"
        f"📌 Паттерны провалов:\n{_bullets(result.get('patterns', []))}\n\n"
        f"❓ Слабые намерения:\n{_bullets(result.get('weak_intents', []))}\n\n"
        f"💡 Добавить в system prompt:\n{_bullets(result.get('prompt_additions', []))}\n\n"
        f"📝 {result.get('summary', '—')}"
    )


@shared_task(
    name="services_app.tasks.analyze_failed_conversations",
    bind=True, max_retries=1, ignore_result=False,
)
def analyze_failed_conversations(self, openai_client=None):
    """LLM meta-analysis последних ANALYSIS_SAMPLE неудавшихся диалогов.

    Phase 2 Learning Roadmap. Запускается weekly в понедельник 06:00 МСК.

    1. Выбирает до ANALYSIS_SAMPLE закрытых conversations с outcome ∈
       {abandoned, redirected, error}, по newest-first.
    2. Сериализует каждый диалог (user+assistant messages, до 10 на диалог).
    3. Отправляет в LLM — получает JSON с patterns/weak_intents/prompt_additions.
    4. Шлёт Telegram-отчёт администратору.
    5. Возвращает result dict для Celery result backend / мониторинга.
    """
    failed_outcomes = [
        Conversation.Outcome.ABANDONED.value,
        Conversation.Outcome.REDIRECTED.value,
        Conversation.Outcome.ERROR.value,
    ]
    convs = list(
        Conversation.objects
        .filter(is_active=False, outcome__in=failed_outcomes)
        .order_by("-created_at")[:ANALYSIS_SAMPLE]
    )

    if not convs:
        logger.info("analyze_failed_conversations: no failed conversations to analyze")
        return {"sample_count": 0, "skipped": True}

    sample_count = len(convs)
    conv_texts: list[str] = []
    for conv in convs:
        msgs = list(
            Message.objects
            .filter(conversation=conv)
            .order_by("created_at")[:10]
        )
        text = _serialize_conversation(conv, msgs)
        conv_texts.append(text)

    try:
        result = _run_llm_analysis(conv_texts, sample_count, openai_client=openai_client)
    except Exception as exc:  # noqa: BLE001
        logger.exception("analyze_failed_conversations: LLM call failed: %s", exc)
        return {"sample_count": sample_count, "error": str(exc)}

    report = _format_telegram_report(result, sample_count)
    try:
        send_notification_telegram(report)
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyze_failed_conversations: Telegram send failed: %s", exc)

    logger.info(
        "analyze_failed_conversations: analyzed %d convs, %d patterns, %d prompt_additions",
        sample_count,
        len(result.get("patterns") or []),
        len(result.get("prompt_additions") or []),
    )
    # Phase 2.4 «Auto-tune #5»: open auto-PR с предложенными амендментами,
    # если включено и условия выполнены (≥5 failed, неделя с прошлого PR).
    pr_url: str | None = None
    try:
        from services_app.auto_tune import create_amendment_pr
        pr_url = create_amendment_pr(
            amendments=result.get("prompt_additions") or [],
            summary=result.get("summary") or "",
            failed_conv_ids=[str(c.id) for c in convs],
            sample_count=sample_count,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("analyze_failed_conversations: auto-tune PR failed: %s", exc)

    if pr_url:
        try:
            send_notification_telegram(f"🔧 Auto-tune PR создан: {pr_url}")
        except Exception:  # noqa: BLE001
            pass

    return {
        "sample_count": sample_count,
        "patterns": result.get("patterns") or [],
        "weak_intents": result.get("weak_intents") or [],
        "prompt_additions": result.get("prompt_additions") or [],
        "summary": result.get("summary") or "",
        "auto_tune_pr_url": pr_url,
    }


# ─── Phase 2.4 «Auto-tune #1»: few-shot rotation ──────────────────────────


@shared_task(
    name="services_app.tasks.collect_success_examples",
    bind=True, max_retries=1, ignore_result=False,
)
def collect_success_examples(self):
    """Собирает курируемые few-shot примеры из last-week success-диалогов.

    Логика:
    1. Берём conversations с outcome=success за последние 14 дней.
    2. Парсим в user→assistant пары (rendered_text > content).
    3. Дедупим по user_text (lower-cased) против уже сохранённых.
    4. Сохраняем новые как FewShotExample(is_active=True).
    5. Оставляем top-FEWSHOT_KEEP_ACTIVE последних, остальные деактивируем.

    Запускается weekly воскресенье 22:00 МСК.
    """
    cutoff = timezone.now() - timedelta(days=FEWSHOT_LOOKBACK_DAYS)
    convs = (
        Conversation.objects
        .filter(outcome=Conversation.Outcome.SUCCESS.value, last_message_at__gte=cutoff)
        .order_by("-last_message_at")
    )

    existing_user_texts = set(
        FewShotExample.objects
        .values_list("user_text", flat=True)
    )
    existing_lower = {ut.lower().strip() for ut in existing_user_texts}

    created = 0
    for conv in convs:
        msgs = list(
            Message.objects
            .filter(conversation=conv)
            .order_by("created_at")
            .values("role", "content", "rendered_text")
        )
        prev_user: str | None = None
        for m in msgs:
            role = m["role"]
            if role == Message.Role.USER:
                prev_user = (m["content"] or "").strip()
                continue
            if role != Message.Role.ASSISTANT or not prev_user:
                continue
            assistant_text = (m["rendered_text"] or m["content"] or "").strip()
            if (
                len(prev_user) < FEWSHOT_MIN_USER_LEN
                or len(assistant_text) < FEWSHOT_MIN_ASSISTANT_LEN
            ):
                prev_user = None
                continue
            key = prev_user.lower().strip()
            if key in existing_lower:
                prev_user = None
                continue
            FewShotExample.objects.create(
                user_text=prev_user,
                assistant_text=assistant_text,
                source_conversation=conv,
                is_active=True,
            )
            existing_lower.add(key)
            created += 1
            prev_user = None

    # Оставляем топ-N последних активных, остальные деактивируем.
    keep_ids = list(
        FewShotExample.objects
        .filter(is_active=True)
        .order_by("-created_at")[:FEWSHOT_KEEP_ACTIVE]
        .values_list("id", flat=True)
    )
    deactivated = (
        FewShotExample.objects
        .filter(is_active=True)
        .exclude(id__in=keep_ids)
        .update(is_active=False)
    )

    logger.info(
        "collect_success_examples: created=%d deactivated=%d active_count<=%d",
        created, deactivated, FEWSHOT_KEEP_ACTIVE,
    )
    return {"created": created, "deactivated": deactivated}
