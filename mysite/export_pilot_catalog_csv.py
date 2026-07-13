#!/usr/bin/env python
"""Export the pilot salon catalog from mysite → Ayla S3C intake CSV.

One-shot ops bridge: reads mysite's ``services_app`` catalog (the YClients
last-sync data) and writes the CSV that Ayla's ``intake_csv`` command
consumes.

CSV columns (Ayla S3C contract):
    external_service_id,title,duration_min,price_min,price_max,category,staff_ids

Mapping (mysite → CSV):
    ServiceOption.yclients_service_id  -> external_service_id  (key; rows without it are skipped)
    ServiceOption.name / Service.name  -> title
    ServiceOption.duration_min         -> duration_min  (already minutes)
    ServiceOption.price                -> price_min      (single price; price_max left blank)
    Service.category.name              -> category
    Master.yclients_staff_id           -> staff_ids  (';'-joined, masters of the parent Service)

Secrets: DB creds come from mysite's own env/.env — never hard-coded here,
never printed. This script only reads (SELECT); it never writes to mysite.

Usage (from mysite project dir, mysite venv):
    # local sqlite last-sync:
    DB_ENGINE=django.db.backends.sqlite3 DB_NAME=data/db.sqlite3 \
        python export_pilot_catalog_csv.py --out pilot_catalog.csv
    # or against the configured DB (.env):
    python export_pilot_catalog_csv.py --out pilot_catalog.csv
    # verify logic without a DB:
    python export_pilot_catalog_csv.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

CSV_HEADER = [
    "external_service_id", "title", "duration_min",
    "price_min", "price_max", "category", "staff_ids",
]


def _title(service_name: str, option_name: str, duration_min) -> str:
    """Human title, kept distinct per bookable variant.

    Prefer ``<service> — <option>``; when the option has no name, qualify by
    duration so multiple duration variants don't collapse to one name (Ayla's
    SalonService is unique per (tenant, template, name)).
    """
    service_name = (service_name or "").strip()
    option_name = (option_name or "").strip()
    if option_name and option_name != service_name:
        return f"{service_name} — {option_name}" if service_name else option_name
    if service_name:
        return f"{service_name} ({duration_min} мин)" if duration_min else service_name
    return option_name or f"Услуга ({duration_min} мин)"


def build_row(*, yclients_service_id, service_name, option_name,
              duration_min, price, category_name, staff_ids) -> dict:
    """Pure row builder — no ORM, unit-testable."""
    staff = ";".join(
        s.strip() for s in (staff_ids or []) if (s or "").strip()
    )
    return {
        "external_service_id": str(yclients_service_id or "").strip(),
        "title": _title(service_name, option_name, duration_min),
        "duration_min": "" if duration_min is None else int(duration_min),
        "price_min": "" if price is None else price,
        "price_max": "",  # mysite carries a single price per option
        "category": (category_name or "").strip(),
        "staff_ids": staff,
    }


def dedupe_rows(rows: list[dict]) -> list[dict]:
    """One row per external_service_id (YClients is 1:1 with a service_id).

    Representative = smallest duration (falls back to first seen). staff_ids are
    UNIONED across the collapsed rows so specialist coverage isn't lost when a
    YClients id spanned several local variants. Order of first appearance kept.
    """
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in rows:
        key = r["external_service_id"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    out: list[dict] = []
    for key in order:
        members = groups[key]

        def _dur(row):
            d = row["duration_min"]
            return d if isinstance(d, int) else 10 ** 9  # blanks sort last

        rep = min(members, key=_dur)
        staff: list[str] = []
        for m in members:
            for s in (m["staff_ids"].split(";") if m["staff_ids"] else []):
                if s and s not in staff:
                    staff.append(s)
        merged = dict(rep)
        merged["staff_ids"] = ";".join(staff)
        out.append(merged)
    return out


def _self_test() -> int:
    r = build_row(
        yclients_service_id=101, service_name="Массаж", option_name="",
        duration_min=60, price="1500.00", category_name="Массаж",
        staff_ids=["10", " ", "11"],
    )
    assert r["external_service_id"] == "101"
    assert r["title"] == "Массаж (60 мин)"
    assert r["duration_min"] == 60
    assert r["price_min"] == "1500.00"
    assert r["price_max"] == ""
    assert r["staff_ids"] == "10;11"
    r2 = build_row(
        yclients_service_id=102, service_name="Маникюр", option_name="Гель-лак",
        duration_min=90, price=None, category_name="Ногти", staff_ids=[],
    )
    assert r2["title"] == "Маникюр — Гель-лак"
    assert r2["price_min"] == ""
    assert r2["staff_ids"] == ""
    # dedupe: same external id, different durations → one row (min duration),
    # staff unioned across the collapsed rows.
    d = dedupe_rows([
        {"external_service_id": "5", "title": "A", "duration_min": 90,
         "price_min": "200", "price_max": "", "category": "C", "staff_ids": "10"},
        {"external_service_id": "5", "title": "A", "duration_min": 60,
         "price_min": "150", "price_max": "", "category": "C", "staff_ids": "11"},
    ])
    assert len(d) == 1
    assert d[0]["duration_min"] == 60           # representative = min duration
    assert d[0]["staff_ids"] == "10;11"         # unioned
    print("self-test: OK")
    return 0


def _iter_db_rows():
    """Yield built rows from the mysite ORM. Read-only."""
    from services_app.models import ServiceOption  # noqa: E402

    qs = (
        ServiceOption.objects
        .exclude(yclients_service_id__isnull=True)
        .exclude(yclients_service_id="")
        .select_related("service", "service__category")
        .prefetch_related("service__masters")
    )
    for opt in qs.iterator(chunk_size=2000):
        service = opt.service
        category = getattr(getattr(service, "category", None), "name", "")
        masters = service.masters.all() if service else []
        staff_ids = [getattr(m, "yclients_staff_id", "") for m in masters]
        yield build_row(
            yclients_service_id=opt.yclients_service_id,
            service_name=getattr(service, "name", ""),
            option_name=opt.name,
            duration_min=opt.duration_min,
            price=opt.price,
            category_name=category,
            staff_ids=staff_ids,
        )


def _setup_django() -> None:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mysite.settings")
    import django
    django.setup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Export mysite catalog → Ayla intake CSV.")
    parser.add_argument("--out", default="-", help="Output CSV path ('-' = stdout).")
    parser.add_argument("--self-test", action="store_true", help="Run pure-logic checks, no DB.")
    parser.add_argument(
        "--no-dedupe", action="store_true",
        help="Keep every ServiceOption row (default: one row per YClients id).",
    )
    args = parser.parse_args()

    if args.self_test:
        return _self_test()

    _setup_django()

    rows = [r for r in _iter_db_rows() if r["external_service_id"]]
    raw_count = len(rows)
    if not args.no_dedupe:
        rows = dedupe_rows(rows)

    handle = sys.stdout if args.out == "-" else open(args.out, "w", newline="", encoding="utf-8")
    try:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if handle is not sys.stdout:
            handle.close()

    # Counts only — never dump catalog contents to the log.
    mode = "raw" if args.no_dedupe else "deduped by yclients_service_id"
    sys.stderr.write(
        f"exported {len(rows)} row(s) ({mode}) from {raw_count} option(s)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
