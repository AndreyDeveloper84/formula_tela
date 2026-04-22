"""Fuzzy-matching между SEO-кластерами и запросами из Яндекс.Вебмастера.

Лемматизация через pymorphy3 — приводит падежи и формы к initial form
(«массажа/массажу/массажем» → «массаж»), затем token-overlap.
"""
import re
from functools import lru_cache

import pymorphy3

_MORPH = pymorphy3.MorphAnalyzer()

STOP_WORDS = {
    "в", "на", "и", "или", "по", "с", "без", "для", "от", "до", "из",
    "у", "за", "под", "над", "при", "как", "о", "об",
}
TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)


@lru_cache(maxsize=20000)
def _lemma(word: str) -> str:
    return _MORPH.parse(word)[0].normal_form


def tokens(phrase: str) -> frozenset:
    """Разбивает фразу на токены, убирает стоп-слова, лемматизирует."""
    return frozenset(
        _lemma(w) for w in TOKEN_RE.findall(phrase.lower())
        if w not in STOP_WORDS and len(w) >= 2
    )


def cluster_match(kw_tokens: frozenset, q_tokens: frozenset, min_overlap: float = 0.5) -> bool:
    """Keyword совпал с запросом, если ≥50% его токенов присутствуют в запросе.

    Для keyword'ов из ≤2 токенов требуется полное совпадение — иначе
    короткие вроде «массаж пенза» цепляли бы любой запрос со словом «пенза».
    """
    if not kw_tokens:
        return False
    overlap = len(kw_tokens & q_tokens)
    if len(kw_tokens) <= 2:
        return overlap == len(kw_tokens)
    return overlap / len(kw_tokens) >= min_overlap
