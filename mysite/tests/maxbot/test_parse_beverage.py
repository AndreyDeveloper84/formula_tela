"""Phase 3.1 Part 2D.1 T01: parse_beverage hybrid regex+LLM parser."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_parse_beverage_water_with_volume():
    """«250 мл воды» → {voda, 250}."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("250 мл воды")
    assert result == {"beverage_slug": "voda", "ml": 250}


@pytest.mark.asyncio
async def test_parse_beverage_coffee_no_volume_uses_default():
    """«выпила кофе» → {kofe_chernyi, 200} (default serving)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("выпила кофе")
    assert result == {"beverage_slug": "kofe_chernyi", "ml": 200}


@pytest.mark.asyncio
async def test_parse_beverage_glass_unit():
    """«стакан воды» → {voda, 250} (стакан = 250 мл)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("стакан воды")
    assert result == {"beverage_slug": "voda", "ml": 250}


@pytest.mark.asyncio
async def test_parse_beverage_bottle_water():
    """«бутылка воды» → {voda, 500}."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("бутылка воды")
    assert result == {"beverage_slug": "voda", "ml": 500}


@pytest.mark.asyncio
async def test_parse_beverage_wine_glass():
    """«бокал вина» → {vino, 150} (бокал=150)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("бокал вина")
    assert result == {"beverage_slug": "vino", "ml": 150}


@pytest.mark.asyncio
async def test_parse_beverage_litre_explicit():
    """«1 литр воды» → {voda, 1000}."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("1 литр воды")
    assert result == {"beverage_slug": "voda", "ml": 1000}


@pytest.mark.asyncio
async def test_parse_beverage_two_glasses_coffee():
    """«2 чашки кофе» → {kofe_chernyi, 400} (2×чашка(200))."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("2 чашки кофе")
    assert result == {"beverage_slug": "kofe_chernyi", "ml": 400}


@pytest.mark.asyncio
async def test_parse_beverage_unrelated_text_returns_none():
    """«как погода» → None (не напиток)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("как погода")
    assert result is None


@pytest.mark.asyncio
async def test_parse_beverage_empty_returns_none():
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("")
    assert result is None


@pytest.mark.asyncio
async def test_parse_beverage_specific_pattern_first():
    """«зелёный чай» НЕ должен match'иться на «чай» — более специфичный паттерн."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("зелёный чай")
    assert result == {"beverage_slug": "chai_zelenyi", "ml": 250}


@pytest.mark.asyncio
async def test_parse_beverage_capuccino_specific():
    """«капучино» → kofe_kapuchino (не kofe_chernyi)."""
    from maxbot.ai_parsers import parse_beverage

    result = await parse_beverage("капучино")
    assert result == {"beverage_slug": "kofe_kapuchino", "ml": 250}
