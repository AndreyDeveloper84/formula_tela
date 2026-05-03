"""Hybrid regex+LLM parsers for nutrition anketa (Phase 3 T02).

Используется в `nutrition_anketa.py` FSM — клиент пишет возраст, рост, вес,
аллергии в свободной форме, парсер возвращает структурированное значение
ИЛИ sentinel "REFUSED" для явных отказов («не скажу», «секрет», 🤷).

Стратегия — regex ladder (95% случаев), LLM fallback только если regex
не сработал И длина текста ≤ 30 символов (cost guard от спама/абуза).

Все функции async — вызываются из async-handler'ов FSM анкеты.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("maxbot.ai_parsers")

REFUSED = "REFUSED"

# Cost guard: LLM fallback не вызывается на текстах длиннее этого порога —
# отсекает спам/абуз/free-text сообщения которые точно не возраст/рост/вес.
_LLM_MAX_LEN = 30

_LLM_MODEL = "gpt-4o-mini"

# Маркеры явного отказа называть значение
_REFUSAL_MARKERS = (
    "не скажу",
    "не отвечу",
    "секрет",
    "не твоё дело",
    "не твое дело",
    "пропусти",
    "🤷",
)


def _is_refusal(text: str) -> bool:
    normalized = text.lower().strip()
    return any(marker in normalized for marker in _REFUSAL_MARKERS)


# ─── parse_age ──────────────────────────────────────────────────────────────


_PARSE_AGE_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_age_value",
        "description": "Извлечь возраст в годах из свободного текста на русском.",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {
                    "type": ["integer", "null"],
                    "description": "Возраст в годах (5..120). null если не удалось определить.",
                },
                "refused": {
                    "type": "boolean",
                    "description": "True если клиент явно отказался называть возраст.",
                },
            },
            "required": ["value", "refused"],
        },
    },
}


async def parse_age(text: str, *, openai_client: Any = None) -> int | str | None:
    """Распознаёт возраст. Возвращает int 5..120, "REFUSED" или None.

    Regex hit'ы: "25", " 25 ", "25 лет", "мне 25".
    LLM fallback (gpt-4o-mini) для словесных форм типа «тридцать», но только
    если len(text) ≤ 30 — экономия на спаме.
    """
    if _is_refusal(text):
        return REFUSED
    match = re.search(r"\b(\d{1,3})\b", text)
    if match:
        n = int(match.group(1))
        if 5 <= n <= 120:
            return n

    if openai_client is None or len(text) > _LLM_MAX_LEN:
        return None
    return await _llm_parse_int(
        text,
        openai_client=openai_client,
        tool=_PARSE_AGE_TOOL,
        valid_range=(5, 120),
    )


# ─── parse_height ───────────────────────────────────────────────────────────


_PARSE_HEIGHT_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_height_value",
        "description": "Извлечь рост в сантиметрах из свободного текста на русском.",
        "parameters": {
            "type": "object",
            "properties": {
                "value": {
                    "type": ["integer", "null"],
                    "description": "Рост в см (100..250). null если не удалось.",
                },
                "refused": {"type": "boolean"},
            },
            "required": ["value", "refused"],
        },
    },
}


async def parse_height(text: str, *, openai_client: Any = None) -> int | str | None:
    """Распознаёт рост в сантиметрах. Возвращает int 100..250, "REFUSED" или None.

    Поддерживает форматы: "170", "170 см", "1.75", "1,75", "1м75", "1 м 75".
    LLM fallback для "5'7" / других нестандартных форм если len ≤ 30.
    """
    if _is_refusal(text):
        return REFUSED

    cleaned = text.strip().lower()

    # Формат "1м75" / "1 м 75" — метры + см
    m = re.fullmatch(r"\s*([12])\s*[мm]\s*(\d{1,2})\s*", cleaned)
    if m:
        meters, cm = int(m.group(1)), int(m.group(2))
        total = meters * 100 + cm
        if 100 <= total <= 250:
            return total

    # Десятичная запись метров: "1.75" / "1,75" / "1.75 м"
    m = re.fullmatch(r"\s*([12])[.,](\d{1,2})\s*[мm]?\s*", cleaned)
    if m:
        whole, frac = m.group(1), m.group(2).ljust(2, "0")
        total = int(whole) * 100 + int(frac)
        if 100 <= total <= 250:
            return total

    # Целое число (с опц. " см"). Достаточно найти первое число от 100 до 250.
    m = re.search(r"\b(\d{2,3})\b", cleaned)
    if m:
        n = int(m.group(1))
        if 100 <= n <= 250:
            return n

    if openai_client is None or len(text) > _LLM_MAX_LEN:
        return None
    return await _llm_parse_int(
        text,
        openai_client=openai_client,
        tool=_PARSE_HEIGHT_TOOL,
        valid_range=(100, 250),
    )


# ─── parse_weight ───────────────────────────────────────────────────────────


_PARSE_WEIGHT_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_weight_value",
        "description": (
            "Извлечь вес в килограммах из свободного русского текста. "
            "Поддержи диапазоны (например 65-75) и приблизительные оценки."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "value": {
                    "type": ["integer", "null"],
                    "description": "Вес в кг (30..250). Для диапазона — среднее.",
                },
                "exact": {"type": "boolean"},
                "range": {
                    "type": ["array", "null"],
                    "description": "[low, high] если был указан диапазон, иначе null.",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "refused": {"type": "boolean"},
            },
            "required": ["value", "exact", "range", "refused"],
        },
    },
}


def _weight_in_range(n: int) -> bool:
    return 30 <= n <= 250


async def parse_weight(text: str, *, openai_client: Any = None) -> dict | str | None:
    """Распознаёт вес в кг. Возвращает dict {value, exact, range} / "REFUSED" / None.

    Форматы: "65", "65 кг", "65.5", "65,5", "65-75" (диапазон), "около 65".
    """
    if _is_refusal(text):
        return REFUSED

    cleaned = text.strip().lower()

    # Диапазон "65-75" / "65 - 75" / "от 65 до 75"
    m = re.search(r"(\d{2,3})\s*(?:-|—|–|до)\s*(\d{2,3})", cleaned)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        if _weight_in_range(lo) and _weight_in_range(hi):
            return {"value": (lo + hi) // 2, "exact": False, "range": (lo, hi)}

    # Приблизительный маркер: «около», «примерно», «где-то», «~»
    is_approx = bool(
        re.search(r"\b(около|примерно|где-?то|приблизительно)\b|[~≈]", cleaned)
    )

    # Десятичный: "65.5" / "65,5" — округляем вниз до int
    m = re.search(r"\b(\d{2,3})[.,](\d{1,2})\b", cleaned)
    if m:
        n = int(m.group(1))
        if _weight_in_range(n):
            return {"value": n, "exact": not is_approx, "range": None}

    # Целое число
    m = re.search(r"\b(\d{2,3})\b", cleaned)
    if m:
        n = int(m.group(1))
        if _weight_in_range(n):
            return {"value": n, "exact": not is_approx, "range": None}

    if openai_client is None or len(text) > _LLM_MAX_LEN:
        return None
    return await _llm_parse_weight(text, openai_client=openai_client)


async def _llm_parse_weight(text: str, *, openai_client: Any) -> dict | str | None:
    try:
        resp = await openai_client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[{"role": "user", "content": text}],
            tools=[_PARSE_WEIGHT_TOOL],
            tool_choice={"type": "function", "function": {"name": "parse_weight_value"}},
        )
    except Exception:  # noqa: BLE001
        logger.exception("ai_parsers: LLM weight parse failed")
        return None

    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)
    if not tool_calls:
        return None
    try:
        args = json.loads(tool_calls[0].function.arguments or "{}")
    except (json.JSONDecodeError, AttributeError):
        return None

    if args.get("refused") is True:
        return REFUSED
    value = args.get("value")
    if not isinstance(value, int) or not _weight_in_range(value):
        return None

    rng = args.get("range")
    if isinstance(rng, list) and len(rng) == 2 and all(isinstance(x, int) for x in rng):
        rng_tuple = (rng[0], rng[1])
    else:
        rng_tuple = None

    return {
        "value": value,
        "exact": bool(args.get("exact", True)),
        "range": rng_tuple,
    }


# ─── parse_allergies ────────────────────────────────────────────────────────


# slug → набор русских корневых слов. Регистронезависимое substring-matching.
_ALLERGY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "dairy": ("молочк", "молоко", "молочн", "лактоз", "сыр", "творог"),
    "nuts": ("орех", "арахис", "фундук", "миндал"),
    "gluten": ("глютен", "пшениц"),
    "citrus": ("цитрус", "апельсин", "лимон", "мандарин"),
    "eggs": ("яйц", "яичн"),
    "fish": ("рыб", "морепродукт"),
    "honey": ("мёд", "мед "),  # «мед» как подстрока чтобы не ловить «медицин»
    "soy": ("соев", "соя"),
    "chocolate": ("шоколад", "какао"),
}

_VAGUE_MARKERS = (
    "много чего",
    "много всего",
    "куча",
    "разное",
    "не помню",
    "много",
)

_NEGATIVE_MARKERS = (
    "нет",
    "никаких",
    "никаки",
    "ничего",
)


_PARSE_ALLERGIES_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_allergies_value",
        "description": (
            "Извлечь slug-список аллергий из свободного русского текста. "
            "Используй стандартные slug'и: dairy, nuts, gluten, citrus, eggs, "
            "fish, honey, soy, chocolate. Для нестандартных — придумай адекватный "
            "англоязычный slug (например 'nightshades' для пасленовых)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "vague": {
                    "type": "boolean",
                    "description": "True если клиент сказал что-то размытое и нужно уточнить.",
                },
                "refused": {"type": "boolean"},
            },
            "required": ["items", "vague", "refused"],
        },
    },
}


def _detect_allergy_slugs(text: str) -> list[str]:
    """Substring-matching по словарю русских корней — порядок не важен."""
    found: list[str] = []
    for slug, roots in _ALLERGY_KEYWORDS.items():
        if any(root in text for root in roots):
            found.append(slug)
    return found


async def parse_allergies(
    text: str, *, openai_client: Any = None
) -> dict | str:
    """Распознаёт список аллергий. Возвращает {items, vague} или "REFUSED".

    `vague=True` означает что клиент дал размытый ответ («много чего»),
    caller-FSM может задать уточняющий вопрос.
    """
    if _is_refusal(text):
        return REFUSED

    cleaned = text.strip().lower()

    # Negative-сильный маркер. «нет» как самостоятельное слово/фраза.
    if cleaned in _NEGATIVE_MARKERS or any(
        re.fullmatch(rf"{m}[!.\s]*", cleaned) for m in _NEGATIVE_MARKERS
    ):
        return {"items": [], "vague": False}

    # Vague-маркер
    is_vague = any(marker in cleaned for marker in _VAGUE_MARKERS)
    if is_vague:
        return {"items": [], "vague": True}

    # Прямой slug-match
    slugs = _detect_allergy_slugs(cleaned)
    if slugs:
        return {"items": slugs, "vague": False}

    # Cost guard для LLM — длинные тексты/мусор → vague.
    if openai_client is None or len(text) > _LLM_MAX_LEN:
        return {"items": [], "vague": True}

    return await _llm_parse_allergies(text, openai_client=openai_client)


async def _llm_parse_allergies(text: str, *, openai_client: Any) -> dict | str:
    try:
        resp = await openai_client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[{"role": "user", "content": text}],
            tools=[_PARSE_ALLERGIES_TOOL],
            tool_choice={"type": "function", "function": {"name": "parse_allergies_value"}},
        )
    except Exception:  # noqa: BLE001
        logger.exception("ai_parsers: LLM allergies parse failed")
        return {"items": [], "vague": True}

    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)
    if not tool_calls:
        return {"items": [], "vague": True}
    try:
        args = json.loads(tool_calls[0].function.arguments or "{}")
    except (json.JSONDecodeError, AttributeError):
        return {"items": [], "vague": True}

    if args.get("refused") is True:
        return REFUSED

    items = args.get("items") or []
    if not isinstance(items, list):
        items = []
    items = [s for s in items if isinstance(s, str) and s.strip()]
    return {"items": items, "vague": bool(args.get("vague", False))}


async def _llm_parse_int(
    text: str,
    *,
    openai_client: Any,
    tool: dict,
    valid_range: tuple[int, int],
) -> int | str | None:
    """Один LLM-вызов с tool-use, возвращает int / REFUSED / None.

    Используется parse_age и parse_height — оба возвращают int в диапазоне.
    """
    try:
        resp = await openai_client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[{"role": "user", "content": text}],
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": tool["function"]["name"]}},
        )
    except Exception:  # noqa: BLE001
        logger.exception("ai_parsers: LLM call failed for tool %s", tool["function"]["name"])
        return None

    msg = resp.choices[0].message
    tool_calls = getattr(msg, "tool_calls", None)
    if not tool_calls:
        return None
    try:
        args = json.loads(tool_calls[0].function.arguments or "{}")
    except (json.JSONDecodeError, AttributeError):
        return None

    if args.get("refused") is True:
        return REFUSED
    value = args.get("value")
    if not isinstance(value, int):
        return None
    lo, hi = valid_range
    if lo <= value <= hi:
        return value
    return None
