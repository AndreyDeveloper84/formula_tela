"""Phase 2.4 «Auto-tune #5» — auto-PR с амендментами prompt'а."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _set_env(monkeypatch, **kwargs):
    for k, v in kwargs.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)


def test_disabled_returns_none(monkeypatch):
    from services_app.auto_tune import create_amendment_pr
    _set_env(monkeypatch, AUTO_TUNE_ENABLED="0", AUTO_TUNE_GITHUB_PAT="x")
    url = create_amendment_pr(
        amendments=["rule"], summary="x", failed_conv_ids=["a"]*10,
        sample_count=10,
    )
    assert url is None


def test_no_pat_returns_none(monkeypatch):
    from services_app.auto_tune import create_amendment_pr
    _set_env(monkeypatch, AUTO_TUNE_ENABLED="1", AUTO_TUNE_GITHUB_PAT="")
    url = create_amendment_pr(
        amendments=["rule"], summary="x", failed_conv_ids=["a"]*10,
        sample_count=10,
    )
    assert url is None


def test_below_threshold_returns_none(monkeypatch):
    from services_app.auto_tune import create_amendment_pr, MIN_FAILED_CONVS
    _set_env(monkeypatch, AUTO_TUNE_ENABLED="1", AUTO_TUNE_GITHUB_PAT="x")
    url = create_amendment_pr(
        amendments=["rule"], summary="x",
        failed_conv_ids=["a"], sample_count=MIN_FAILED_CONVS - 1,
    )
    assert url is None


def test_no_amendments_returns_none(monkeypatch):
    from services_app.auto_tune import create_amendment_pr
    _set_env(monkeypatch, AUTO_TUNE_ENABLED="1", AUTO_TUNE_GITHUB_PAT="x")
    url = create_amendment_pr(
        amendments=[], summary="x", failed_conv_ids=["a"]*10,
        sample_count=10,
    )
    assert url is None


def test_rate_limited_returns_none(monkeypatch, tmp_path):
    """Если lock-файл < MIN_DAYS_BETWEEN_PRS дней назад — skip."""
    from datetime import datetime
    from services_app import auto_tune
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(auto_tune, "LOCK_FILE", tmp_path / "audits/auto_pr_lock.json")
    auto_tune.LOCK_FILE.parent.mkdir(parents=True)
    auto_tune.LOCK_FILE.write_text(json.dumps({
        "last_run": datetime.now().isoformat(),
        "pr_url": "https://example.com/pull/1",
    }))
    _set_env(monkeypatch, AUTO_TUNE_ENABLED="1", AUTO_TUNE_GITHUB_PAT="x")
    url = auto_tune.create_amendment_pr(
        amendments=["rule"], summary="x", failed_conv_ids=["a"]*10,
        sample_count=10,
    )
    assert url is None


def test_can_open_pr_after_week(monkeypatch, tmp_path):
    """Lock-файл старше недели → разрешено."""
    from datetime import datetime, timedelta
    from services_app import auto_tune
    monkeypatch.setattr(auto_tune, "LOCK_FILE", tmp_path / "lock.json")
    auto_tune.LOCK_FILE.write_text(json.dumps({
        "last_run": (datetime.now() - timedelta(days=10)).isoformat(),
        "pr_url": "old",
    }))
    assert auto_tune.can_open_pr_now() is True


def test_amendment_block_format():
    from services_app.auto_tune import _build_amendment_block
    block = _build_amendment_block(
        amendments=["Когда клиент пишет 'спасибо' — поблагодарить тёплым словом",
                    "На вопрос про скидки — направить в раздел акций"],
        summary="Бот не справляется с благодарностями и вопросами про скидки",
        sample_count=8,
    )
    assert "AUTO-TUNE" in block
    assert "AT1." in block
    assert "AT2." in block
    assert "8 failed" in block


def test_patch_prompt_inserts_block(tmp_path):
    """Marker найден → вставка перед 'Цель:'."""
    from services_app.auto_tune import _patch_prompt_file
    p = tmp_path / "prompt.py"
    p.write_text(
        'TPL = """preamble\n\nЦель: помочь клиенту дойти до записи через ИНСТРУМЕНТЫ.\n"""',
        encoding="utf-8",
    )
    block = "NEW BLOCK CONTENT"
    ok = _patch_prompt_file(p, block)
    assert ok is True
    text = p.read_text(encoding="utf-8")
    assert "NEW BLOCK CONTENT" in text
    # Block ДО маркера, маркер сохранён
    idx_block = text.index("NEW BLOCK CONTENT")
    idx_marker = text.index("Цель: помочь клиенту")
    assert idx_block < idx_marker


def test_patch_prompt_marker_missing(tmp_path):
    from services_app.auto_tune import _patch_prompt_file
    p = tmp_path / "prompt.py"
    p.write_text("TPL = 'no marker here'", encoding="utf-8")
    ok = _patch_prompt_file(p, "block")
    assert ok is False


def test_create_pr_happy_path(monkeypatch, tmp_path):
    """End-to-end mock: clone → patch → push → gh pr create → URL записан."""
    from services_app import auto_tune
    monkeypatch.setattr(auto_tune, "LOCK_FILE", tmp_path / "audits/lock.json")
    _set_env(monkeypatch,
             AUTO_TUNE_ENABLED="1",
             AUTO_TUNE_GITHUB_PAT="github_pat_TEST",
             )

    # Mock subprocess.run — каждый вызов успешен
    def fake_run(cmd, cwd, env=None, capture_output=True, text=True, check=True):
        result = MagicMock()
        result.stdout = ""
        result.stderr = ""
        result.returncode = 0
        # Эмулим клонирование: создаём минимальный prompt.py
        if cmd[:2] == ["git", "clone"]:
            repo = Path(cmd[-1])
            (repo / "mysite/maxbot").mkdir(parents=True)
            (repo / "mysite/maxbot/ai_prompts.py").write_text(
                'TPL = """preamble\nЦель: помочь клиенту дойти до записи через ИНСТРУМЕНТЫ."""',
                encoding="utf-8",
            )
            (repo / ".git").mkdir()
        if cmd[:2] == ["gh", "pr"]:
            result.stdout = "https://github.com/AndreyDeveloper84/formula_tela/pull/9999\n"
        return result

    monkeypatch.setattr(auto_tune.subprocess, "run", fake_run)

    url = auto_tune.create_amendment_pr(
        amendments=["AT правило 1", "AT правило 2"],
        summary="LLM нашёл паттерны",
        failed_conv_ids=[f"conv-{i}" for i in range(8)],
        sample_count=8,
    )
    assert url == "https://github.com/AndreyDeveloper84/formula_tela/pull/9999"
    # Lock-файл записан
    assert auto_tune.LOCK_FILE.exists()
    data = json.loads(auto_tune.LOCK_FILE.read_text())
    assert data["pr_url"] == url


def test_create_pr_subprocess_failure(monkeypatch, tmp_path):
    """Если git/gh упал — возвращаем None, не падаем."""
    import subprocess as sp
    from services_app import auto_tune
    monkeypatch.setattr(auto_tune, "LOCK_FILE", tmp_path / "lock.json")
    _set_env(monkeypatch,
             AUTO_TUNE_ENABLED="1",
             AUTO_TUNE_GITHUB_PAT="x",
             )

    def fake_run(*args, **kwargs):
        raise sp.CalledProcessError(
            returncode=1, cmd=args[0], output="", stderr="auth fail",
        )

    monkeypatch.setattr(auto_tune.subprocess, "run", fake_run)
    url = auto_tune.create_amendment_pr(
        amendments=["rule"], summary="x", failed_conv_ids=["a"]*10,
        sample_count=10,
    )
    assert url is None
