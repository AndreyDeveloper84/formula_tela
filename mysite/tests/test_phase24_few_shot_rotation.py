"""Phase 2.4 «Auto-tune #1» — collect_success_examples + prompt injection."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone
from model_bakery import baker

from services_app.models import (
    BotUser, Conversation, FewShotExample, Message,
)
from services_app.tasks import (
    FEWSHOT_KEEP_ACTIVE,
    collect_success_examples,
)


pytestmark = pytest.mark.django_db


_uid_counter = [10000]


def _make_conv(*, outcome: str, last_message_offset_days: int = 0) -> Conversation:
    _uid_counter[0] += 1
    bot_user = baker.make(BotUser, max_user_id=_uid_counter[0])
    conv = baker.make(
        Conversation,
        bot_user=bot_user,
        outcome=outcome,
        is_active=False,
        last_message_at=timezone.now() - timedelta(days=last_message_offset_days),
    )
    return conv


def _add_pair(conv: Conversation, user_text: str, assistant_text: str,
              rendered_text: str = "") -> None:
    Message.objects.create(
        conversation=conv, role=Message.Role.USER, content=user_text,
    )
    Message.objects.create(
        conversation=conv, role=Message.Role.ASSISTANT,
        content=assistant_text, rendered_text=rendered_text or assistant_text,
    )


def test_collect_creates_examples_from_success_conv():
    conv = _make_conv(outcome=Conversation.Outcome.SUCCESS.value)
    _add_pair(
        conv, "хочу массаж от боли в спине",
        "Поняла, сейчас подберу. Подходят классический массаж и массаж спины.",
    )

    result = collect_success_examples()
    assert result["created"] >= 1

    examples = list(FewShotExample.objects.filter(is_active=True))
    assert len(examples) == 1
    assert examples[0].user_text == "хочу массаж от боли в спине"
    assert "классический массаж" in examples[0].assistant_text


def test_collect_skips_failed_outcomes():
    conv = _make_conv(outcome=Conversation.Outcome.ABANDONED.value)
    _add_pair(conv, "запиши меня на массаж", "Какой массаж интересует?")

    collect_success_examples()
    assert FewShotExample.objects.count() == 0


def test_collect_dedupes_by_user_text():
    conv1 = _make_conv(outcome=Conversation.Outcome.SUCCESS.value)
    _add_pair(conv1, "хочу массаж спины", "Подобрала: Денис, Инна.")
    collect_success_examples()
    assert FewShotExample.objects.count() == 1

    conv2 = _make_conv(outcome=Conversation.Outcome.SUCCESS.value)
    _add_pair(conv2, "Хочу массаж спины", "Подобрала ещё: Инна.")
    collect_success_examples()
    # Тот же текст (case-insensitive) — не дублируется
    assert FewShotExample.objects.count() == 1


def test_collect_keeps_top_n_active():
    # Создаём KEEP_ACTIVE+5 разных пар → активных должно остаться KEEP_ACTIVE
    for i in range(FEWSHOT_KEEP_ACTIVE + 5):
        conv = _make_conv(outcome=Conversation.Outcome.SUCCESS.value)
        _add_pair(conv, f"хочу услугу номер {i} пожалуйста",
                  f"Конечно, услуга {i} — отличный выбор!")
    collect_success_examples()
    active = FewShotExample.objects.filter(is_active=True).count()
    assert active == FEWSHOT_KEEP_ACTIVE


def test_collect_skips_too_short_pairs():
    conv = _make_conv(outcome=Conversation.Outcome.SUCCESS.value)
    _add_pair(conv, "ок", "Записал")  # both too short
    collect_success_examples()
    assert FewShotExample.objects.count() == 0


def test_collect_uses_rendered_text_over_content():
    conv = _make_conv(outcome=Conversation.Outcome.SUCCESS.value)
    _add_pair(
        conv, "запиши меня на лазер пожалуйста",
        assistant_text="",  # tool_call assistant — content пустой
        rendered_text="Конечно. На какую зону хотите запись?\n\n• Голени с коленями\n• Бикини",
    )
    collect_success_examples()
    ex = FewShotExample.objects.first()
    assert ex is not None
    assert "Голени" in ex.assistant_text


def test_render_system_prompt_includes_active_examples():
    conv = _make_conv(outcome=Conversation.Outcome.SUCCESS.value)
    _add_pair(conv, "хочу массаж от боли в спине",
              "Поняла, сейчас подберу классический массаж.")
    collect_success_examples()

    from maxbot.ai_context import MasterContext
    from maxbot.ai_prompts import render_system_prompt

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(),
        summary_text="(test)",
    )
    prompt = render_system_prompt(
        today=date(2026, 4, 30), client_name="Тест",
        bookings_count=0, master_context=ctx,
    )
    assert "ПРИМЕРЫ ХОРОШИХ ОТВЕТОВ" in prompt
    assert "хочу массаж от боли в спине" in prompt


def test_render_system_prompt_no_block_when_no_examples():
    from maxbot.ai_context import MasterContext
    from maxbot.ai_prompts import render_system_prompt

    ctx = MasterContext(
        candidates=[], candidate_ids=frozenset(),
        candidate_service_ids=frozenset(),
        summary_text="(test)",
    )
    prompt = render_system_prompt(
        today=date(2026, 4, 30), client_name="Тест",
        bookings_count=0, master_context=ctx,
    )
    assert "ПРИМЕРЫ ХОРОШИХ ОТВЕТОВ" not in prompt
