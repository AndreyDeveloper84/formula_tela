"""One-shot creator: Linear project «Phase 3 — Nutrition Tracker (Ayla)» + 7 issues.

Reads issue descriptions from docs/plans/maxbot-phase3-linear-issues.md
and creates issues via Linear GraphQL API. Uses HTTPS proxy because
api.linear.app is blocked in RF.

Usage:
    LINEAR_API_TOKEN=lin_api_... \
    HTTPS_PROXY=http://user:pass@host:port \
    python scripts/create_linear_phase3_backlog.py

Idempotency: re-running creates duplicates — safe to run only once.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import httpx

LINEAR_API = "https://api.linear.app/graphql"
TEAM_ID = "9caf1205-31eb-4163-a1e9-424602c3522a"  # DRF (Ayla)
PROJECT_NAME = "Phase 3 — Nutrition Tracker (Ayla)"
PROJECT_DESCRIPTION = (
    "Ayla backend endpoints for MAX-bot Phase 3 nutrition tracker: "
    "profile + water + patterns + extensions to scan/summary."
)
SPEC_NOTION_URL = (
    "https://www.notion.so/Ayla-Backend-Phase-3-Nutrition-Endpoints-Spec-"
    "354b0dab295581da9456ebadf8e15192"
)
PROJECT_CONTENT = f"""# Phase 3 — Nutrition Tracker (Ayla backend)

**Spec:** [Notion]({SPEC_NOTION_URL})

**MAX-bot side plan:** `~/.claude/plans/hashed-forging-map.md` (T01..T25 в три фазы 3.1/3.2/3.3)

## Context

MAX-бот «Формула тела» (Penza, salon ниша) расширяется функцией nutrition-tracker.
Архитектурное решение: вся nutrition data живёт в Ayla, MAX-бот — thin UX client.

Этот project — backend endpoints в Ayla:
- DRF-300..DRF-303: блокирующие для Phase 3.1 (онбординг + анкета + вода + photo refactor + дневной отчёт)
- DRF-304..DRF-305: блокирующие для Phase 3.3 (pattern detection + returning success)
- DRF-306: backlog Phase 3.4 (event-driven webhooks)

## Что делать backend-команде

1. Прочитать spec в Notion (link выше)
2. Inline-комментарии в Notion-странице к спорным местам
3. Принять/изменить acceptance criteria каждой issue
4. Проставить estimates по своему опыту
5. Запланировать на спринт

**MAX-бот side mock**: `mysite/tests/fixtures/ayla_mock.py` (24 напитка seed,
business logic для override/milestone/restore — соответствует spec'у).
"""


PRIORITY_HIGH = 2
PRIORITY_MEDIUM = 3
PRIORITY_LOW = 4

ISSUES = [
    {
        "title": "DRF-300 — NutritionProfile API (GET/POST /profile/)",
        "priority": PRIORITY_HIGH,
        "estimate": 5,
        "section": "DRF-300 — NutritionProfile API",
    },
    {
        "title": "DRF-301 — Beverage catalog (GET /beverages/) + seed 50 напитков",
        "priority": PRIORITY_HIGH,
        "estimate": 2,
        "section": "DRF-301 — Beverage catalog",
    },
    {
        "title": "DRF-302 — Water tracking (POST/DELETE/GET /water/)",
        "priority": PRIORITY_HIGH,
        "estimate": 5,
        "section": "DRF-302 — Water tracking",
    },
    {
        "title": "DRF-303 — Расширения существующих endpoints (caption + AI comment)",
        "priority": PRIORITY_HIGH,
        "estimate": 3,
        "section": "DRF-303 — Расширения существующих endpoints",
    },
    {
        "title": "DRF-304 — Pattern detection (GET /patterns/)",
        "priority": PRIORITY_MEDIUM,
        "estimate": 8,
        "section": "DRF-304 — Pattern detection",
    },
    {
        "title": "DRF-305 — Returning success insight",
        "priority": PRIORITY_MEDIUM,
        "estimate": 2,
        "section": "DRF-305 — Returning success insight",
    },
    {
        "title": "DRF-306 — Webhook для cross-system events (Phase 3.4)",
        "priority": PRIORITY_LOW,
        "estimate": 5,
        "section": "DRF-306 — Webhook для cross-system events",
    },
]


def graphql(token: str, proxies: dict, query: str, variables: dict) -> dict:
    """POST GraphQL query with retry — RF proxy is flaky."""
    import time
    headers = {
        "Authorization": token,  # NO Bearer for personal API key
        "Content-Type": "application/json",
    }
    last_exc: Exception | None = None
    for attempt in range(1, 6):
        try:
            resp = httpx.post(
                LINEAR_API,
                headers=headers,
                json={"query": query, "variables": variables},
                proxy=proxies.get("https"),
                timeout=30.0,
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("errors"):
                print(f"GraphQL errors: {json.dumps(body['errors'], indent=2)}")
                sys.exit(1)
            return body["data"]
        except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadTimeout) as exc:
            last_exc = exc
            wait = 2 ** attempt
            print(f"  [!] {type(exc).__name__} on attempt {attempt}/5, retry in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"GraphQL failed after 5 attempts: {last_exc}")


def parse_issue_descriptions(md_path: Path) -> dict[str, str]:
    """Extract description for each issue section from the markdown file."""
    text = md_path.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    # Split on "## " — each issue is its own H2 section.
    parts = re.split(r"\n## ", text)
    for p in parts[1:]:  # skip preamble
        first_line, _, rest = p.partition("\n")
        title = first_line.strip()
        # Use the part of title before first newline as section key.
        sections[title] = rest.strip()
    return sections


def main() -> None:
    token = os.environ.get("LINEAR_API_TOKEN")
    if not token:
        print("LINEAR_API_TOKEN env var required")
        sys.exit(2)

    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not https_proxy:
        print("WARNING: HTTPS_PROXY not set — Linear API may be unreachable from RF")
    proxies = {"https": https_proxy} if https_proxy else {}

    md_path = Path("docs/plans/maxbot-phase3-linear-issues.md")
    if not md_path.exists():
        print(f"Markdown not found: {md_path}")
        sys.exit(2)
    descriptions = parse_issue_descriptions(md_path)
    print(f"Parsed {len(descriptions)} issue sections from {md_path}")

    # 1. Find or create project (idempotent).
    print(f"Looking for existing project '{PROJECT_NAME}'...")
    find_project_q = """
    query FindProjects($filter: ProjectFilter) {
      projects(filter: $filter, first: 50) {
        nodes { id name url }
      }
    }
    """
    found = graphql(token, proxies, find_project_q, {
        "filter": {"name": {"eq": PROJECT_NAME}},
    })
    nodes = found["projects"]["nodes"]
    if nodes:
        project = nodes[0]
        project_id = project["id"]
        print(f"  [OK] Reusing existing project: {project['url']}")
    else:
        print(f"  Creating new project in DRF team...")
        create_project_q = """
        mutation CreateProject($input: ProjectCreateInput!) {
          projectCreate(input: $input) {
            success
            project { id name url }
          }
        }
        """
        proj_data = graphql(token, proxies, create_project_q, {
            "input": {
                "name": PROJECT_NAME,
                "description": PROJECT_DESCRIPTION,
                "content": PROJECT_CONTENT,
                "teamIds": [TEAM_ID],
                "state": "planned",
            },
        })
        project = proj_data["projectCreate"]["project"]
        project_id = project["id"]
        print(f"  [OK] Project created: {project['url']}")

    # 1b. Skip issues that already exist with same title.
    find_issues_q = """
    query FindIssues($filter: IssueFilter) {
      issues(filter: $filter, first: 50) {
        nodes { id identifier title url }
      }
    }
    """
    existing = graphql(token, proxies, find_issues_q, {
        "filter": {"project": {"id": {"eq": project_id}}},
    })
    existing_titles = {i["title"] for i in existing["issues"]["nodes"]}
    if existing_titles:
        print(f"  Found {len(existing_titles)} existing issues in project, will skip dups.")

    # 2. Create issues.
    create_issue_q = """
    mutation CreateIssue($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue { id identifier url title }
      }
    }
    """
    created: list[dict] = []
    for i, spec in enumerate(ISSUES, 1):
        section_key = spec["section"]
        # Find matching section by prefix.
        desc = ""
        for key, body in descriptions.items():
            if key.startswith(section_key):
                desc = body
                break
        if not desc:
            print(f"  [!] No description found for '{section_key}' — using empty")

        # Append spec link footer.
        full_desc = f"{desc}\n\n---\n\n**Spec:** [Notion]({SPEC_NOTION_URL})  \n**MAX-bot plan:** `~/.claude/plans/hashed-forging-map.md`"

        if spec["title"] in existing_titles:
            print(f"  [{i}/{len(ISSUES)}] SKIP (already exists): {spec['title'][:70]}")
            continue

        print(f"  [{i}/{len(ISSUES)}] Creating: {spec['title'][:70]}...")
        data = graphql(token, proxies, create_issue_q, {
            "input": {
                "title": spec["title"],
                "description": full_desc,
                "teamId": TEAM_ID,
                "projectId": project_id,
                "priority": spec["priority"],
                "estimate": spec["estimate"],
            },
        })
        issue = data["issueCreate"]["issue"]
        created.append(issue)
        print(f"      [OK] {issue['identifier']}: {issue['url']}")

    print(f"\n✅ Done. Project + {len(created)} issues created.")
    print(f"\nProject URL: {project['url']}")
    print("Issues:")
    for issue in created:
        print(f"  - {issue['identifier']}: {issue['url']}")


if __name__ == "__main__":
    main()
