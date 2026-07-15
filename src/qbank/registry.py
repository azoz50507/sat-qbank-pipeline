"""Source registry builder (Phase 1).

Loads the vetted source list from ``data/registry/seed_sources.json``,
stores it in a SQLite database, exports a flat CSV for reporting, and
prints a vetting summary.

The seed file is the human-curated single source of truth: every entry
records the license found, links to the evidence, the vetting decision
(approved / conditional / rejected), and the reason for that decision.

Usage:
    python src/qbank/registry.py
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = PROJECT_ROOT / "data" / "registry"
SEED_PATH = REGISTRY_DIR / "seed_sources.json"
DB_PATH = REGISTRY_DIR / "sources.db"
CSV_PATH = REGISTRY_DIR / "source_registry.csv"

SCHEMA = """
DROP TABLE IF EXISTS sources;
CREATE TABLE sources (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    publisher        TEXT,
    source_type      TEXT,
    landing_url      TEXT,
    file_urls        TEXT,          -- JSON array of direct file URLs (may be empty)
    publication_year INTEGER,
    license          TEXT NOT NULL,
    evidence         TEXT NOT NULL, -- JSON array of {url, note, retrieved}
    status           TEXT NOT NULL CHECK (status IN ('approved', 'conditional', 'rejected')),
    usage_tag        TEXT NOT NULL, -- PUBLIC_DOMAIN / CC_BY_SA_* / RESTRICTED_* / DO_NOT_COLLECT
    priority         TEXT,
    decision_reason  TEXT NOT NULL,
    notes            TEXT,
    vetting_date     TEXT NOT NULL
);
"""

CSV_COLUMNS = [
    "id", "name", "publisher", "source_type", "status", "usage_tag",
    "priority", "license", "decision_reason", "publication_year",
    "landing_url", "evidence_urls", "vetting_date",
]


def load_seed(seed_path: Path = SEED_PATH) -> dict:
    with seed_path.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_database(seed: dict, db_path: Path = DB_PATH) -> int:
    """(Re)populate the SQLite registry from the seed. Returns row count."""
    vetting_date = seed["vetting_date"]
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        rows = [
            (
                s["id"], s["name"], s.get("publisher"), s.get("source_type"),
                s.get("landing_url"), json.dumps(s.get("file_urls", [])),
                s.get("publication_year"), s["license"],
                json.dumps(s["evidence"]), s["status"],
                s.get("usage_tag", "DO_NOT_COLLECT"), s.get("priority"),
                s["decision_reason"], s.get("notes", ""), vetting_date,
            )
            for s in seed["sources"]
        ]
        conn.executemany(
            "INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def export_csv(seed: dict, csv_path: Path = CSV_PATH) -> None:
    """Flatten the registry to a CSV suitable for reports/spreadsheets."""
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for s in seed["sources"]:
            writer.writerow({
                "id": s["id"],
                "name": s["name"],
                "publisher": s.get("publisher", ""),
                "source_type": s.get("source_type", ""),
                "status": s["status"],
                "usage_tag": s.get("usage_tag", "DO_NOT_COLLECT"),
                "priority": s.get("priority") or "",
                "license": s["license"],
                "decision_reason": s["decision_reason"],
                "publication_year": s.get("publication_year") or "",
                "landing_url": s.get("landing_url", ""),
                "evidence_urls": " | ".join(e["url"] for e in s["evidence"]),
                "vetting_date": seed["vetting_date"],
            })


def print_summary(seed: dict) -> None:
    sources = seed["sources"]
    by_status = Counter(s["status"] for s in sources)
    by_type = Counter(s["source_type"] for s in sources)

    print("=" * 62)
    print("PHASE 1 - SOURCE REGISTRY SUMMARY")
    print(f"Vetting date: {seed['vetting_date']}   Total candidates: {len(sources)}")
    print("=" * 62)

    print("\nDecisions:")
    for status in ("approved", "conditional", "rejected"):
        print(f"  {status:<12} {by_status.get(status, 0):>3}")

    print("\nBy source type:")
    for src_type, count in by_type.most_common():
        print(f"  {src_type:<26} {count:>3}")

    print("\nApproved / conditional sources:")
    header = f"  {'id':<36} {'status':<12} {'priority':<9} usage_tag"
    print(header)
    print("  " + "-" * (len(header) + 20))
    for s in sources:
        if s["status"] in ("approved", "conditional"):
            tag = s.get("usage_tag", "DO_NOT_COLLECT")
            print(f"  {s['id']:<36} {s['status']:<12} {s.get('priority') or '-':<9} {tag}")

    print("\nRejected sources (reason):")
    for s in sources:
        if s["status"] == "rejected":
            reason = s["decision_reason"].split(".")[0]
            print(f"  {s['id']:<36} {reason}")
    print()


def main() -> int:
    if not SEED_PATH.exists():
        print(f"ERROR: seed file not found: {SEED_PATH}", file=sys.stderr)
        return 1

    seed = load_seed()
    count = build_database(seed)
    export_csv(seed)
    print_summary(seed)
    print(f"SQLite registry : {DB_PATH.relative_to(PROJECT_ROOT)} ({count} rows)")
    print(f"CSV export      : {CSV_PATH.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
