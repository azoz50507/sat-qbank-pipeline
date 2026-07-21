"""Question extraction driver (Phase 5).

Walks every ``content`` page, picks the best available text for it -
the embedded text layer for text-routed pages, the Phase 4 OCR text for
image-routed pages whose OCR quality is good/fair - runs the segmenter,
and persists structured question items:

- ``question_items`` table in the registry DB (fully rebuilt each run;
  segmentation is cheap, derived data)
- ``data/qbank/question_items.jsonl`` - the question bank artifact
- ``data/qbank/segmentation_report.csv`` - per-page accounting, including
  pages that were skipped and why

Items inherit the source's usage tag: items derived from RESTRICTED
sources must never leave this machine (data/qbank/ is gitignored).

Usage:
    python src/qbank/extract.py
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qbank.segmenter import item_status, segment_page  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "registry" / "sources.db"
QBANK_DIR = PROJECT_ROOT / "data" / "qbank"
JSONL_PATH = QBANK_DIR / "question_items.jsonl"
REPORT_CSV = QBANK_DIR / "segmentation_report.csv"

ITEMS_SCHEMA = """
DROP TABLE IF EXISTS question_items;
CREATE TABLE question_items (
    item_id           TEXT PRIMARY KEY,
    source_id         TEXT NOT NULL,
    doc               TEXT NOT NULL,
    page_num          INTEGER NOT NULL,
    item_seq          INTEGER NOT NULL,
    number_label      TEXT,
    kind              TEXT,     -- multiple_choice / free_response / unknown
    stem              TEXT,
    choices           TEXT,     -- JSON array
    n_choices         INTEGER,
    flags             TEXT,     -- JSON array
    status            TEXT,     -- ok / needs_review
    extraction_source TEXT,     -- text_layer / ocr
    ocr_mean_conf     REAL,
    usage_tag         TEXT,
    created_at        TEXT
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def page_text_plan(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every content page with its chosen text source and skip reason."""
    return conn.execute(
        """SELECT p.source_id, p.doc, p.page_num, p.route, p.text_path,
                  p.usage_tag,
                  o.ocr_path, o.mean_conf AS ocr_mean_conf,
                  o.quality_flag AS ocr_flag
           FROM pages p
           LEFT JOIN ocr_results o
                  ON o.source_id = p.source_id AND o.doc = p.doc
                 AND o.page_num = p.page_num
           WHERE p.classification = 'content'
           ORDER BY p.source_id, p.doc, p.page_num"""
    ).fetchall()


def choose_text(row: sqlite3.Row) -> tuple[str | None, str, str]:
    """Return (path, extraction_source, skip_reason). path None => skipped."""
    if row["route"] == "text":
        return row["text_path"], "text_layer", ""
    if row["ocr_path"] is None:
        return None, "", "no_ocr_result"
    if row["ocr_flag"] in ("good", "fair"):
        return row["ocr_path"], "ocr", ""
    return None, "", f"ocr_quality_{row['ocr_flag']}"


def main() -> int:
    started = time.time()
    QBANK_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(ITEMS_SCHEMA)

    report_rows: list[dict] = []
    total_items = 0
    now = utc_now()

    with JSONL_PATH.open("w", encoding="utf-8") as jsonl:
        for row in page_text_plan(conn):
            path, source, skip = choose_text(row)
            if path is None:
                report_rows.append({
                    "source_id": row["source_id"], "doc": row["doc"],
                    "page_num": row["page_num"], "items": 0,
                    "extraction_source": "", "skipped_reason": skip,
                })
                continue
            file_path = PROJECT_ROOT / path
            text = file_path.read_text(encoding="utf-8", errors="replace") \
                if file_path.exists() else ""
            items = segment_page(text)
            for seq, item in enumerate(items, start=1):
                status = item_status(item, source, row["ocr_mean_conf"])
                item_id = (f"{row['source_id']}:{row['doc']}:"
                           f"p{row['page_num']:04d}:{seq}")
                record = {
                    "item_id": item_id,
                    "source_id": row["source_id"],
                    "doc": row["doc"],
                    "page_num": row["page_num"],
                    "item_seq": seq,
                    "number_label": item.number_label,
                    "kind": item.kind,
                    "stem": item.stem,
                    "choices": item.choices,
                    "flags": item.flags,
                    "status": status,
                    "extraction_source": source,
                    "ocr_mean_conf": row["ocr_mean_conf"] if source == "ocr" else None,
                    "usage_tag": row["usage_tag"],
                    "created_at": now,
                }
                jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
                conn.execute(
                    """INSERT INTO question_items VALUES
                       (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (item_id, row["source_id"], row["doc"], row["page_num"],
                     seq, item.number_label, item.kind, item.stem,
                     json.dumps(item.choices), len(item.choices),
                     json.dumps(item.flags), status, source,
                     record["ocr_mean_conf"], row["usage_tag"], now),
                )
            total_items += len(items)
            report_rows.append({
                "source_id": row["source_id"], "doc": row["doc"],
                "page_num": row["page_num"], "items": len(items),
                "extraction_source": source, "skipped_reason": "",
            })
    conn.commit()

    with REPORT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(report_rows[0].keys()))
        writer.writeheader()
        writer.writerows(report_rows)

    # ---- summary ----------------------------------------------------------
    print("=" * 66)
    print("PHASE 5 - QUESTION SEGMENTATION SUMMARY")
    print("=" * 66)
    pages_used = sum(1 for r in report_rows if not r["skipped_reason"])
    pages_skipped = len(report_rows) - pages_used
    print(f"\nContent pages: {len(report_rows)}  "
          f"(segmented {pages_used}, skipped {pages_skipped})")
    print(f"Question items extracted: {total_items}")

    print(f"\n{'kind':<18} {'items':>6}    {'status':<14} {'items':>6}")
    print("-" * 52)
    kinds = conn.execute(
        "SELECT kind, COUNT(*) FROM question_items GROUP BY kind ORDER BY 2 DESC"
    ).fetchall()
    statuses = conn.execute(
        "SELECT status, COUNT(*) FROM question_items GROUP BY status ORDER BY 2 DESC"
    ).fetchall()
    for i in range(max(len(kinds), len(statuses))):
        left = f"{kinds[i][0]:<18} {kinds[i][1]:>6}" if i < len(kinds) else " " * 25
        right = f"{statuses[i][0]:<14} {statuses[i][1]:>6}" if i < len(statuses) else ""
        print(f"{left}    {right}")

    print(f"\n{'source':<36} {'items':>6} {'mc':>5} {'free':>5} {'ok':>5} {'review':>7}")
    print("-" * 72)
    for r in conn.execute(
        """SELECT source_id, COUNT(*) AS n,
                  SUM(kind='multiple_choice'), SUM(kind='free_response'),
                  SUM(status='ok'), SUM(status='needs_review')
           FROM question_items GROUP BY source_id ORDER BY source_id"""
    ):
        print(f"{r[0]:<36} {r[1]:>6} {r[2]:>5} {r[3]:>5} {r[4]:>5} {r[5]:>7}")

    print("\nSkip reasons (pages left out, by design):")
    reasons = {}
    for r in report_rows:
        if r["skipped_reason"]:
            reasons[r["skipped_reason"]] = reasons.get(r["skipped_reason"], 0) + 1
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<24} {n}")

    print(f"\nElapsed: {time.time() - started:.1f}s")
    print(f"Question bank : {JSONL_PATH.relative_to(PROJECT_ROOT)} ({total_items} items)")
    print(f"Page report   : {REPORT_CSV.relative_to(PROJECT_ROOT)}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
