"""Phase 3 T02: hybrid regex+LLM parsers for nutrition anketa.

Покрывает 4 функции из maxbot/ai_parsers.py:
- parse_age, parse_height, parse_weight, parse_allergies

Pattern: regex ladder (95% случаев) → LLM fallback (gpt-4o-mini) →
"REFUSED" sentinel для явных отказов. Cost guard: LLM только если regex
не сработал И длина текста ≤ 30 символов.
"""
from __future__ import annotations

import pytest


# ─── parse_age ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_age_bare_number():
    """Голое число «25» — самый частый ввод, regex hit без LLM."""
    from maxbot.ai_parsers import parse_age

    assert await parse_age("25") == 25


@pytest.mark.asyncio
async def test_parse_age_with_word_let():
    """«25 лет» — частый формат с единицей измерения."""
    from maxbot.ai_parsers import parse_age

    assert await parse_age("25 лет") == 25


@pytest.mark.asyncio
async def test_parse_age_with_prefix_mne():
    """«мне 30» — клиент пишет от первого лица."""
    from maxbot.ai_parsers import parse_age

    assert await parse_age("мне 30") == 30


@pytest.mark.asyncio
async def test_parse_age_refusal_returns_sentinel():
    """«не скажу» — явный отказ → REFUSED, не None."""
    from maxbot.ai_parsers import REFUSED, parse_age

    assert await parse_age("не скажу") == REFUSED


@pytest.mark.asyncio
async def test_parse_age_emoji_refusal_returns_sentinel():
    """🤷 — невербальный отказ тоже REFUSED."""
    from maxbot.ai_parsers import REFUSED, parse_age

    assert await parse_age("🤷") == REFUSED


@pytest.mark.asyncio
async def test_parse_age_out_of_range_returns_none():
    """«250» — out of range (5..120), не доверяем."""
    from maxbot.ai_parsers import parse_age

    assert await parse_age("250") is None


@pytest.mark.asyncio
async def test_parse_age_zero_or_too_young_returns_none():
    """«2» — слишком молодой, скорее опечатка."""
    from maxbot.ai_parsers import parse_age

    assert await parse_age("2") is None


@pytest.mark.asyncio
async def test_parse_age_garbage_returns_none():
    """«привет» — нет числа, нет refusal-маркера → None (caller спросит снова)."""
    from maxbot.ai_parsers import parse_age

    assert await parse_age("привет") is None


@pytest.mark.asyncio
async def test_parse_age_word_form_uses_llm_fallback():
    """«тридцать» — regex не сработает, нужен LLM fallback.

    Тест мокает openai_client.chat.completions.create — реального вызова нет.
    """
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_age

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        tool_calls=[
                            MagicMock(
                                function=MagicMock(
                                    name="parse_age_value",
                                    arguments='{"value": 30}',
                                )
                            )
                        ]
                    )
                )
            ]
        )
    )

    result = await parse_age("тридцать", openai_client=fake_client)
    assert result == 30
    fake_client.chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_parse_age_long_text_skips_llm_fallback():
    """Текст длиннее 30 символов — cost guard, LLM не вызываем, сразу None."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_age

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock()

    long = "длинный текст без чисел на котором не должны тратить токены LLM"
    assert len(long) > 30
    result = await parse_age(long, openai_client=fake_client)

    assert result is None
    fake_client.chat.completions.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_parse_age_llm_returns_refused_sentinel():
    """LLM может вернуть «refused» если распознал отказ в нестандартной форме."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import REFUSED, parse_age

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        tool_calls=[
                            MagicMock(
                                function=MagicMock(
                                    name="parse_age_value",
                                    arguments='{"value": null, "refused": true}',
                                )
                            )
                        ]
                    )
                )
            ]
        )
    )

    result = await parse_age("это моё личное", openai_client=fake_client)
    assert result == REFUSED


@pytest.mark.asyncio
async def test_parse_age_llm_no_tool_call_returns_none():
    """LLM не вызвал tool — значит распознать не удалось → None."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_age

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(tool_calls=None))]
        )
    )

    result = await parse_age("гммм", openai_client=fake_client)
    assert result is None


# ─── parse_height ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_height_bare_centimeters():
    """«170» — самый частый ввод роста, считаем что это уже сантиметры."""
    from maxbot.ai_parsers import parse_height

    assert await parse_height("170") == 170


@pytest.mark.asyncio
async def test_parse_height_meters_with_dot():
    """«1.75» — десятичные метры → 175 см."""
    from maxbot.ai_parsers import parse_height

    assert await parse_height("1.75") == 175


@pytest.mark.asyncio
async def test_parse_height_meters_with_comma():
    """«1,75» — русская десятичная запятая → 175 см."""
    from maxbot.ai_parsers import parse_height

    assert await parse_height("1,75") == 175


@pytest.mark.asyncio
async def test_parse_height_meters_word_form():
    """«1м75» / «1 м 75» — частый формат в чате."""
    from maxbot.ai_parsers import parse_height

    assert await parse_height("1м75") == 175
    assert await parse_height("1 м 75") == 175


@pytest.mark.asyncio
async def test_parse_height_with_unit_cm():
    """«170 см» — явная единица измерения, остаёмся в сантиметрах."""
    from maxbot.ai_parsers import parse_height

    assert await parse_height("170 см") == 170


@pytest.mark.asyncio
async def test_parse_height_refusal():
    """«не скажу» — отказ → REFUSED."""
    from maxbot.ai_parsers import REFUSED, parse_height

    assert await parse_height("не скажу") == REFUSED


@pytest.mark.asyncio
async def test_parse_height_out_of_range_returns_none():
    """«300» см — нереально, не доверяем."""
    from maxbot.ai_parsers import parse_height

    assert await parse_height("300") is None


@pytest.mark.asyncio
async def test_parse_height_too_short_returns_none():
    """«50» см — нереально (карлики тоже выше); range 100..250."""
    from maxbot.ai_parsers import parse_height

    assert await parse_height("50") is None


@pytest.mark.asyncio
async def test_parse_height_garbage_returns_none():
    """«примерно» — нет числа → None."""
    from maxbot.ai_parsers import parse_height

    assert await parse_height("примерно") is None


@pytest.mark.asyncio
async def test_parse_height_foot_inch_uses_llm_fallback():
    """«5'7» — foot/inch формат, regex не справляется — LLM fallback."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_height

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        tool_calls=[
                            MagicMock(
                                function=MagicMock(
                                    name="parse_height_value",
                                    arguments='{"value": 170, "refused": false}',
                                )
                            )
                        ]
                    )
                )
            ]
        )
    )

    result = await parse_height("5'7", openai_client=fake_client)
    assert result == 170


@pytest.mark.asyncio
async def test_parse_height_long_text_skips_llm():
    """Cost guard — длинный текст не отправляем в LLM."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_height

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock()

    long = "ну я не уверена сколько у меня см но точно высокая я очень"
    assert len(long) > 30
    result = await parse_height(long, openai_client=fake_client)

    assert result is None
    fake_client.chat.completions.create.assert_not_awaited()


# ─── parse_weight ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_weight_exact_number():
    """«65» — точное значение."""
    from maxbot.ai_parsers import parse_weight

    result = await parse_weight("65")
    assert result == {"value": 65, "exact": True, "range": None}


@pytest.mark.asyncio
async def test_parse_weight_with_unit_kg():
    """«65 кг» — единица измерения, остаёмся точным."""
    from maxbot.ai_parsers import parse_weight

    result = await parse_weight("65 кг")
    assert result == {"value": 65, "exact": True, "range": None}


@pytest.mark.asyncio
async def test_parse_weight_range_dash():
    """«65-75» — диапазон, value = среднее, exact=False, range зафиксирован."""
    from maxbot.ai_parsers import parse_weight

    result = await parse_weight("65-75")
    assert result == {"value": 70, "exact": False, "range": (65, 75)}


@pytest.mark.asyncio
async def test_parse_weight_approximate_okolo():
    """«около 65» — приблизительно, exact=False."""
    from maxbot.ai_parsers import parse_weight

    result = await parse_weight("около 65")
    assert result == {"value": 65, "exact": False, "range": None}


@pytest.mark.asyncio
async def test_parse_weight_decimal():
    """«65.5» / «65,5» — с запятой/точкой → округляем до 65 (целочисленный value).

    На текущем этапе мы хранили килограммы как int в Ayla profile schema —
    округляем вниз чтобы не врать клиенту в сторону завышения.
    """
    from maxbot.ai_parsers import parse_weight

    assert (await parse_weight("65.5"))["value"] == 65
    assert (await parse_weight("65,5"))["value"] == 65


@pytest.mark.asyncio
async def test_parse_weight_refusal():
    from maxbot.ai_parsers import REFUSED, parse_weight

    assert await parse_weight("не скажу") == REFUSED


@pytest.mark.asyncio
async def test_parse_weight_out_of_range_returns_none():
    """«500 кг» — нереально."""
    from maxbot.ai_parsers import parse_weight

    assert await parse_weight("500") is None


@pytest.mark.asyncio
async def test_parse_weight_too_low_returns_none():
    """«20» — ниже минимума 30 кг."""
    from maxbot.ai_parsers import parse_weight

    assert await parse_weight("20") is None


@pytest.mark.asyncio
async def test_parse_weight_garbage_returns_none():
    from maxbot.ai_parsers import parse_weight

    assert await parse_weight("привет мир") is None


@pytest.mark.asyncio
async def test_parse_weight_word_form_uses_llm():
    """«семьдесят» — regex не справится, LLM fallback."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_weight

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        tool_calls=[
                            MagicMock(
                                function=MagicMock(
                                    name="parse_weight_value",
                                    arguments='{"value": 70, "exact": true, "range": null, "refused": false}',
                                )
                            )
                        ]
                    )
                )
            ]
        )
    )

    result = await parse_weight("семьдесят", openai_client=fake_client)
    assert result == {"value": 70, "exact": True, "range": None}


@pytest.mark.asyncio
async def test_parse_weight_long_text_skips_llm():
    """Cost guard — длинный текст не пускаем в LLM."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_weight

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock()

    long = "не помню точно но обычно где-то от шестидесяти до семидесяти пяти"
    assert len(long) > 30
    result = await parse_weight(long, openai_client=fake_client)
    assert result is None
    fake_client.chat.completions.create.assert_not_awaited()


# ─── parse_allergies ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_allergies_empty_no():
    """«нет» → пустой items, vague=False (твёрдый ответ)."""
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("нет")
    assert result == {"items": [], "vague": False}


@pytest.mark.asyncio
async def test_parse_allergies_empty_nikakikh():
    """«никаких» → empty items, vague=False."""
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("никаких")
    assert result == {"items": [], "vague": False}


@pytest.mark.asyncio
async def test_parse_allergies_dairy_keyword():
    """«молочка» → slug `dairy`."""
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("молочка")
    assert "dairy" in result["items"]
    assert result["vague"] is False


@pytest.mark.asyncio
async def test_parse_allergies_multiple_separated_by_comma():
    """«молочка, орехи» → два slug'а."""
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("молочка, орехи")
    assert set(result["items"]) == {"dairy", "nuts"}
    assert result["vague"] is False


@pytest.mark.asyncio
async def test_parse_allergies_gluten_keyword():
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("глютен")
    assert "gluten" in result["items"]


@pytest.mark.asyncio
async def test_parse_allergies_eggs_and_citrus():
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("яйца и цитрус")
    assert set(result["items"]) == {"eggs", "citrus"}


@pytest.mark.asyncio
async def test_parse_allergies_vague_marker():
    """«много чего» → vague=True, items пуст (caller спросит подробнее)."""
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("много чего")
    assert result == {"items": [], "vague": True}


@pytest.mark.asyncio
async def test_parse_allergies_garbage_returns_empty_vague():
    """Бессмыслица — пустой items + vague=True (caller разберётся)."""
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("привет")
    assert result["items"] == []
    assert result["vague"] is True


@pytest.mark.asyncio
async def test_parse_allergies_refusal():
    from maxbot.ai_parsers import REFUSED, parse_allergies

    assert await parse_allergies("не скажу") == REFUSED


@pytest.mark.asyncio
async def test_parse_allergies_fish_and_honey():
    """«рыба, мёд» — два менее частых slug'а."""
    from maxbot.ai_parsers import parse_allergies

    result = await parse_allergies("рыба, мёд")
    assert set(result["items"]) == {"fish", "honey"}


@pytest.mark.asyncio
async def test_parse_allergies_llm_fallback_for_unknown():
    """«не переношу пасленовые» — нет в slug-словаре, нужен LLM."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_allergies

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(
        return_value=MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(
                        tool_calls=[
                            MagicMock(
                                function=MagicMock(
                                    name="parse_allergies_value",
                                    arguments='{"items": ["nightshades"], "vague": false, "refused": false}',
                                )
                            )
                        ]
                    )
                )
            ]
        )
    )

    result = await parse_allergies("пасленовые", openai_client=fake_client)
    assert result == {"items": ["nightshades"], "vague": False}


@pytest.mark.asyncio
async def test_parse_allergies_long_text_skips_llm():
    """Cost guard для длинного описания — vague=True без LLM."""
    from unittest.mock import AsyncMock, MagicMock

    from maxbot.ai_parsers import parse_allergies

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock()

    long = "ну вот раньше не было аллергий а сейчас я не уверена надо проверить"
    assert len(long) > 30
    result = await parse_allergies(long, openai_client=fake_client)

    assert result == {"items": [], "vague": True}
    fake_client.chat.completions.create.assert_not_awaited()
