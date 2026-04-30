"""Auto-tune #5 — открывает GitHub PR с амендментами prompt'а на основе
выводов analyze_failed_conversations.

Поток:
1. analyze_failed_conversations возвращает `prompt_additions` от LLM.
2. Если включено `AUTO_TUNE_ENABLED=1` и условия выполнены (≥5 failed convs,
   неделя с прошлого auto-PR), `create_amendment_pr` клонит репо в tmp,
   дописывает rules в ai_prompts.py, коммитит, пушит ветку, открывает PR
   через `gh` CLI с PAT из `AUTO_TUNE_GITHUB_PAT`.
3. Менеджер ревьюит PR в UI и решает мержить или нет — auto-merge нет.

Безопасность:
- PAT — fine-grained, только `Contents:write` + `Pull requests:write` для
  одного repo.
- Tmp-clone, не трогает прод working tree.
- Lock-файл `audits/auto_pr_lock.json` ограничивает к 1 PR в неделю.
- PR помечается label `auto-tune` (для фильтрации в /github/pulls).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path


logger = logging.getLogger("services_app.auto_tune")

LOCK_FILE = Path("audits/auto_pr_lock.json")
MIN_DAYS_BETWEEN_PRS = 7
MIN_FAILED_CONVS = 5
GITHUB_REPO = "AndreyDeveloper84/formula_tela"
GIT_AUTHOR_NAME = "Auto-tune Bot"
GIT_AUTHOR_EMAIL = "auto-tune@formulatela58.ru"


def is_enabled() -> bool:
    return os.environ.get("AUTO_TUNE_ENABLED", "0").lower() in ("1", "true", "yes")


def can_open_pr_now() -> bool:
    """Rate limit: ≥1 неделя с прошлого PR."""
    if not LOCK_FILE.exists():
        return True
    try:
        data = json.loads(LOCK_FILE.read_text())
        last = datetime.fromisoformat(data["last_run"])
        return (datetime.now() - last) >= timedelta(days=MIN_DAYS_BETWEEN_PRS)
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_tune: lock file read failed: %s — allowing PR", exc)
        return True


def _record_pr_run(pr_url: str) -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps({
        "last_run": datetime.now().isoformat(),
        "pr_url": pr_url,
    }, indent=2))


def _build_amendment_block(amendments: list[str], summary: str,
                           sample_count: int) -> str:
    """Формирует текст блока правил для вставки в SYSTEM_PROMPT_TEMPLATE."""
    today = datetime.now().strftime("%Y-%m-%d")
    lines = [
        "",
        f"# ── AUTO-TUNE {today} — на основе анализа {sample_count} failed диалогов",
        f"# Сводка LLM: {summary[:200]}",
        "# Менеджер должен проверить эти правила перед мержем PR.",
        "AUTO-TUNE ПРАВИЛА (применяй приоритетно):",
    ]
    for i, rule in enumerate(amendments[:5], 1):
        cleaned = rule.strip().replace("\n", " ")[:300]
        lines.append(f"AT{i}. {cleaned}")
    return "\n".join(lines) + "\n"


def _patch_prompt_file(path: Path, block: str) -> bool:
    """Вставляет block перед строкой `Цель: помочь клиенту...` в template.

    Возвращает True если файл изменён, False если marker не найден.
    """
    text = path.read_text(encoding="utf-8")
    marker = "Цель: помочь клиенту дойти до записи через ИНСТРУМЕНТЫ."
    if marker not in text:
        logger.warning("auto_tune: prompt marker not found, skipping")
        return False
    new_text = text.replace(marker, block + "\n" + marker)
    path.write_text(new_text, encoding="utf-8")
    return True


def _run(cmd: list[str], cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Wrapper around subprocess.run с capture_output + text для удобства логов."""
    logger.debug("auto_tune: running %s in %s", " ".join(cmd[:3]), cwd)
    return subprocess.run(
        cmd, cwd=str(cwd), env=env, capture_output=True, text=True, check=True,
    )


def create_amendment_pr(
    *,
    amendments: list[str],
    summary: str,
    failed_conv_ids: list[str],
    sample_count: int,
) -> str | None:
    """Создаёт ветку + коммит + PR с амендментами prompt'а.

    Возвращает URL созданного PR или None если auto-tune disabled / не время /
    нет PAT / amendments пустой / git/gh упали.

    Параметры:
    - amendments: prompt_additions от LLM (до 5 правил)
    - summary: текстовая сводка от LLM (для PR description)
    - failed_conv_ids: UUID диалогов которые легли в анализ (для аудита)
    - sample_count: сколько диалогов проанализировано (для PR description)
    """
    if not is_enabled():
        logger.info("auto_tune: AUTO_TUNE_ENABLED!=1, skipping")
        return None
    if not amendments:
        logger.info("auto_tune: no amendments to apply, skipping")
        return None
    if sample_count < MIN_FAILED_CONVS:
        logger.info(
            "auto_tune: only %d failed convs (<%d threshold), skipping",
            sample_count, MIN_FAILED_CONVS,
        )
        return None
    if not can_open_pr_now():
        logger.info("auto_tune: rate-limited (1 PR per %d days), skipping",
                    MIN_DAYS_BETWEEN_PRS)
        return None
    pat = os.environ.get("AUTO_TUNE_GITHUB_PAT", "")
    if not pat:
        logger.warning("auto_tune: AUTO_TUNE_GITHUB_PAT not set, skipping")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    branch = f"auto-tune/prompt-{today}"

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        repo = tmp_path / "formula_tela"
        clone_url = f"https://x-access-token:{pat}@github.com/{GITHUB_REPO}.git"
        try:
            _run(["git", "clone", "--depth", "1", "--branch", "main",
                  clone_url, str(repo)], cwd=tmp_path)
            _run(["git", "config", "user.name", GIT_AUTHOR_NAME], cwd=repo)
            _run(["git", "config", "user.email", GIT_AUTHOR_EMAIL], cwd=repo)
            _run(["git", "checkout", "-b", branch], cwd=repo)

            prompt_path = repo / "mysite" / "maxbot" / "ai_prompts.py"
            block = _build_amendment_block(amendments, summary, sample_count)
            if not _patch_prompt_file(prompt_path, block):
                return None

            _run(["git", "add", "mysite/maxbot/ai_prompts.py"], cwd=repo)
            commit_msg = (
                f"chore(auto-tune): prompt amendments {today}\n\n"
                f"Auto-generated from analysis of {sample_count} failed "
                f"conversations. Review carefully before merging.\n\n"
                f"🤖 Generated by services_app.auto_tune"
            )
            _run(["git", "commit", "-m", commit_msg], cwd=repo)
            _run(["git", "push", "origin", branch], cwd=repo)

            body_lines = [
                "## Auto-generated prompt amendments",
                "",
                f"**Sample size:** {sample_count} failed conversations",
                f"**LLM summary:** {summary[:500]}",
                "",
                "### Предлагаемые правила (вставлены в SYSTEM_PROMPT_TEMPLATE)",
                "",
            ]
            for i, rule in enumerate(amendments[:5], 1):
                body_lines.append(f"{i}. {rule.strip()[:300]}")
            body_lines += ["", "### Source conversations", ""]
            for cid in failed_conv_ids[:10]:
                body_lines.append(
                    f"- `{cid}` — `/admin/services_app/conversation/{cid}/change/`"
                )
            body_lines += [
                "", "---",
                "⚠ Auto-tune предлагает правила на основе LLM-анализа failed диалогов.",
                "Не мержи на автопилоте — проверь что правила не противоречат существующим.",
                "Если плохо — закрывай PR без merge, ничего на проде не сломается.",
            ]
            body = "\n".join(body_lines)

            env = {**os.environ, "GH_TOKEN": pat, "GITHUB_TOKEN": pat}
            pr_result = _run(
                ["gh", "pr", "create", "--base", "main", "--head", branch,
                 "--title", f"chore(auto-tune): prompt amendments {today}",
                 "--body", body, "--label", "auto-tune"],
                cwd=repo, env=env,
            )
            url = pr_result.stdout.strip()
            _record_pr_run(url)
            logger.info("auto_tune: created PR %s", url)
            return url
        except subprocess.CalledProcessError as exc:
            logger.exception(
                "auto_tune: subprocess failed: %s\nstdout: %s\nstderr: %s",
                exc, exc.stdout, exc.stderr,
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("auto_tune: unexpected error: %s", exc)
            return None
