"""Phase 2.4 T04a — voice_examples курируемые few-shot диалоги."""
from __future__ import annotations

import pytest

from maxbot.voice_examples import (
    Example,
    FORMULA_TELA_EXAMPLES,
    render_examples_block,
)


def test_formula_tela_examples_count():
    """5 эталонных диалогов покрывают Sprint 1 сценарии."""
    assert len(FORMULA_TELA_EXAMPLES) == 5


def test_examples_are_immutable():
    """Example — frozen dataclass (нельзя модифицировать на лету)."""
    ex = FORMULA_TELA_EXAMPLES[0]
    with pytest.raises((AttributeError, TypeError, Exception)):  # FrozenInstanceError
        ex.user = "different"


def test_render_examples_block_default():
    block = render_examples_block()
    assert "ЭТАЛОННЫЕ ДИАЛОГИ" in block
    # Все 5 диалогов в блоке
    for i in range(1, 6):
        assert f"{i}. Клиент:" in block


def test_render_examples_block_empty():
    """Пустой список → пустая строка (не вставлять секцию)."""
    assert render_examples_block([]) == ""


def test_render_examples_block_custom():
    custom = [Example(user="Привет", assistant="Здравствуйте!")]
    block = render_examples_block(custom)
    assert "Привет" in block
    assert "Здравствуйте!" in block


def test_examples_cover_sprint1_scenarios():
    """Sanity: examples покрывают greeting/discovery/health/blocked/post-confirm."""
    user_msgs = " ".join(ex.user.lower() for ex in FORMULA_TELA_EXAMPLES)
    assistant_msgs = " ".join(ex.assistant.lower() for ex in FORMULA_TELA_EXAMPLES)
    # greeting
    assert "здравствуйте" in user_msgs
    # discovery (расслабиться)
    assert "расслабляющее" in user_msgs or "устала" in user_msgs
    # health screening
    assert "антицеллюлитный" in user_msgs
    # blocked
    assert "беременности" in user_msgs or "варикоз" in user_msgs
    # post-confirm
    assert "записала" in assistant_msgs
