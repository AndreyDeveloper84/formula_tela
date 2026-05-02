"""One-shot uploader: docs/plans/maxbot-phase3-ayla-spec.md → Notion page.

Usage:
    NOTION_TOKEN=ntn_... python scripts/upload_spec_to_notion.py \
        --page-id 354b0dab-2955-81da-9456-ebadf8e15192 \
        --file docs/plans/maxbot-phase3-ayla-spec.md

Parses markdown into Notion block objects (heading_1/2/3, paragraph, bulleted/
numbered list items, code, divider, table, quote) and POSTs in batches of 95
to /v1/blocks/{page_id}/children. Idempotency is the caller's responsibility —
re-running appends duplicate content.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

import requests

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
BATCH_SIZE = 95
RICH_TEXT_LIMIT = 2000  # Notion per-rich-text-content limit


def rich_text(content: str, *, bold: bool = False, italic: bool = False,
              code: bool = False, link: str | None = None) -> dict:
    rt: dict = {
        "type": "text",
        "text": {"content": content[:RICH_TEXT_LIMIT]},
        "annotations": {
            "bold": bold, "italic": italic, "strikethrough": False,
            "underline": False, "code": code, "color": "default",
        },
    }
    if link:
        rt["text"]["link"] = {"url": link}
    return rt


# ─── Inline parsing — bold / italic / code / link ──────────────────────────

INLINE_RE = re.compile(
    r"(\*\*(?P<bold>[^*]+)\*\*)"
    r"|(`(?P<code>[^`]+)`)"
    r"|(\[(?P<lnktxt>[^\]]+)\]\((?P<lnkurl>[^)]+)\))"
)


def parse_inline(text: str) -> list[dict]:
    """Markdown inline → list of rich_text objects."""
    if not text:
        return []
    parts: list[dict] = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            parts.append(rich_text(text[pos:m.start()]))
        if m.group("bold"):
            parts.append(rich_text(m.group("bold"), bold=True))
        elif m.group("code"):
            parts.append(rich_text(m.group("code"), code=True))
        elif m.group("lnktxt"):
            parts.append(rich_text(m.group("lnktxt"), link=m.group("lnkurl")))
        pos = m.end()
    if pos < len(text):
        parts.append(rich_text(text[pos:]))
    return parts or [rich_text(text)]


# ─── Block builders ────────────────────────────────────────────────────────

def heading(level: int, text: str) -> dict:
    return {
        "object": "block",
        "type": f"heading_{level}",
        f"heading_{level}": {"rich_text": parse_inline(text)},
    }


def paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": parse_inline(text)},
    }


def bulleted(text: str) -> dict:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": parse_inline(text)},
    }


def numbered(text: str) -> dict:
    return {
        "object": "block",
        "type": "numbered_list_item",
        "numbered_list_item": {"rich_text": parse_inline(text)},
    }


def code_block(content: str, language: str = "plain text") -> dict:
    # Notion limit: 2000 chars per rich_text, but code block can have multiple
    # rich_texts in one block. Split if needed.
    chunks: list[dict] = []
    for i in range(0, len(content), RICH_TEXT_LIMIT):
        chunks.append(rich_text(content[i:i + RICH_TEXT_LIMIT]))
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": chunks or [rich_text("")], "language": language},
    }


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def quote(text: str) -> dict:
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": parse_inline(text)},
    }


def table_block(rows: list[list[str]], has_header: bool = True) -> dict:
    """Notion table — must have children specified inline."""
    width = max(len(r) for r in rows)
    # Pad short rows.
    padded = [r + [""] * (width - len(r)) for r in rows]
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": has_header,
            "has_row_header": False,
            "children": [
                {
                    "object": "block",
                    "type": "table_row",
                    "table_row": {
                        "cells": [parse_inline(c.strip()) for c in row],
                    },
                }
                for row in padded
            ],
        },
    }


# ─── Markdown → blocks parser ──────────────────────────────────────────────

NOTION_LANG_MAP = {
    "py": "python", "python": "python",
    "js": "javascript", "javascript": "javascript",
    "ts": "typescript", "typescript": "typescript",
    "json": "json", "yaml": "yaml", "yml": "yaml",
    "bash": "bash", "sh": "shell", "shell": "shell",
    "html": "html", "css": "css",
    "sql": "sql", "go": "go",
    "md": "markdown", "markdown": "markdown",
    "": "plain text",
}


def parse_md(md: str) -> list[dict]:
    blocks: list[dict] = []
    lines = md.split("\n")
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # Skip blank lines.
        if not stripped:
            i += 1
            continue

        # Code block: ```lang ... ```
        m = re.match(r"^```(\w*)\s*$", line)
        if m:
            lang = NOTION_LANG_MAP.get(m.group(1).lower(), "plain text")
            code_lines: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            blocks.append(code_block("\n".join(code_lines), lang))
            i += 1  # skip closing ```
            continue

        # Heading.
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            blocks.append(heading(level, m.group(2).strip()))
            i += 1
            continue

        # Divider.
        if re.match(r"^---+\s*$", line):
            blocks.append(divider())
            i += 1
            continue

        # Quote.
        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while i < n and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(quote(" ".join(quote_lines)))
            continue

        # Table — line with pipes, next line is separator.
        if "|" in line and i + 1 < n and re.match(r"^\s*\|?[-:|\s]+\|?\s*$", lines[i + 1]):
            table_rows: list[list[str]] = []
            # Parse header.
            header = [c.strip() for c in line.strip().strip("|").split("|")]
            table_rows.append(header)
            i += 2  # skip header + separator
            while i < n and "|" in lines[i] and lines[i].strip():
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                table_rows.append(row)
                i += 1
            blocks.append(table_block(table_rows, has_header=True))
            continue

        # Bulleted list.
        m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        if m:
            indent = len(m.group(1))
            content = m.group(2)
            # Continuation lines (indented further).
            i += 1
            while i < n:
                cont = re.match(r"^(\s+)(.*)$", lines[i])
                if cont and len(cont.group(1)) > indent and not re.match(r"^(\s*)[-*]\s+", lines[i]):
                    content += " " + cont.group(2).strip()
                    i += 1
                else:
                    break
            blocks.append(bulleted(content))
            continue

        # Numbered list.
        m = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if m:
            content = m.group(3)
            i += 1
            blocks.append(numbered(content))
            continue

        # Paragraph (collect adjacent non-empty non-special lines).
        para_lines: list[str] = [line]
        i += 1
        while i < n:
            nxt = lines[i]
            if (not nxt.strip() or nxt.strip().startswith(("#", "```", "---", ">", "|"))
                    or re.match(r"^(\s*)[-*]\s+", nxt) or re.match(r"^(\s*)\d+\.\s+", nxt)):
                break
            para_lines.append(nxt)
            i += 1
        blocks.append(paragraph(" ".join(l.strip() for l in para_lines)))

    return blocks


# ─── Notion API call ───────────────────────────────────────────────────────

def append_blocks(token: str, page_id: str, blocks: list[dict]) -> None:
    url = f"{NOTION_API}/blocks/{page_id}/children"
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    total = len(blocks)
    sent = 0
    for i in range(0, total, BATCH_SIZE):
        batch = blocks[i:i + BATCH_SIZE]
        resp = requests.patch(url, headers=headers, json={"children": batch}, timeout=30)
        if resp.status_code >= 300:
            print(f"ERROR batch {i}-{i + len(batch)}: HTTP {resp.status_code}")
            print(resp.text[:1000])
            sys.exit(1)
        sent += len(batch)
        print(f"  + uploaded {sent}/{total} blocks")
        time.sleep(0.35)  # Notion rate-limit ~3 req/s


# ─── CLI ───────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--page-id", required=True)
    p.add_argument("--file", required=True, type=Path)
    p.add_argument("--token", default=os.environ.get("NOTION_TOKEN", ""))
    args = p.parse_args()

    if not args.token:
        print("Missing NOTION_TOKEN env var or --token")
        sys.exit(2)
    if not args.file.exists():
        print(f"File not found: {args.file}")
        sys.exit(2)

    md = args.file.read_text(encoding="utf-8")
    blocks = parse_md(md)
    print(f"Parsed {len(blocks)} blocks from {args.file}")
    append_blocks(args.token, args.page_id, blocks)
    print("Done.")


if __name__ == "__main__":
    main()
