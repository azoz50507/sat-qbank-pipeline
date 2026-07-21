"""Question/answer alignment driver (Phase 6).

Pairs each College Board test document with its answer-explanations
document, parses every answer_key page (Phase 3 classification) through
``answers.py``, aligns entries to Phase 5 question items by
(block position, question number), and persists:

- ``qa_alignment`` table (rebuilt each run)
- ``data/qbank/qa_records.jsonl`` - merged question+answer records
- ``data/qbank/alignment_report.csv`` - per-pair accounting

A consistency check verifies that each matched multiple-choice answer
letter actually exists among the item's parsed choices.

Usage:
    python src/qbank/align.py
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qbank.answers import AnswerEntry, align_pair, parse_answer_page  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "registry" / "sources.db"
QBANK_DIR = PROJECT_ROOT / "data" / "qbank"
QA_JSONL = QBANK_DIR / "qa_records.jsonl"
REPORT_CSV = QBANK_DIR / "alignment_report.csv"

TEST_DOC = re.compile(r"^(sat-practice-test-\d+)-digital$")

ALIGN_SCHEMA = """
DROP TABLE IF EXISTS qa_alignment;
CREATE TABLE qa_alignment (
    item_id        TEXT PRIMARY KEY,
    answers_doc    TEXT NOT NULL,
    answer_block   TEXT,
    correct_choice TEXT,
    answer_text    TEXT,
    rationale      TEXT,
    answer_flags   TEXT,   -- JSON array
    consistent     INTEGER, -- 1 = letter exists among the item's choices
    created_at     TEXT
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def doc_pairs(conn: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """(source_id, test_doc, answers_doc) for every pair present in data."""
    docs = {row[0] for row in conn.execute("SELECT DISTINCT doc FROM pages")}
    pairs = []
    for doc in sorted(docs):
        match = TEST_DOC.match(doc)
        if match:
            answers = f"{match.group(1)}-answers-digital"
            if answers in docs:
                source = conn.execute(
                    "SELECT source_id FROM pages WHERE doc=? LIMIT 1", (doc,)
                ).fetchone()[0]
                pairs.append((source, doc, answers))
    return pairs


def answer_blocks_for_doc(conn: sqlite3.Connection, doc: str):
    """Ordered (block_label, {number -> AnswerEntry}) from answer_key pages."""
    blocks: list[tuple[str | None, dict[str, AnswerEntry]]] = []
    pages_parsed = entries_total = 0
    for row in conn.execute(
        """SELECT text_path FROM pages
           WHERE doc=? AND classification='answer_key' ORDER BY page_num""",
        (doc,),
    ):
        path = PROJECT_ROOT / row[0]
        if not path.exists():
            continue
        label, entries = parse_answer_page(
            path.read_text(encoding="utf-8", errors="replace"))
        pages_parsed += 1
        if not entries:
            continue
        entries_total += len(entries)
        if blocks and blocks[-1][0] == label:
            table = blocks[-1][1]
        else:
            table = {}
            blocks.append((label, table))
        for entry in entries:
            table.setdefault(entry.number_label, entry)
    return blocks, pages_parsed, entries_total


def question_items_for_doc(conn: sqlite3.Connection, doc: str):
    """Items in reading order; short-stem items (likely layout junk) are
    kept in the bank but excluded from alignment input."""
    rows = conn.execute(
        """SELECT item_id, number_label, choices, flags FROM question_items
           WHERE doc=? ORDER BY page_num, item_seq""",
        (doc,),
    ).fetchall()
    items = [
        (r[0], r[1]) for r in rows
        if "short_stem" not in json.loads(r[3] or "[]")
    ]
    choices = {r[0]: json.loads(r[2] or "[]") for r in rows}
    return items, choices


def main() -> int:
    started = time.time()
    QBANK_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(ALIGN_SCHEMA)
    now = utc_now()

    report = []
    total_matched = total_unmatched = total_orphans = total_inconsistent = 0

    with QA_JSONL.open("w", encoding="utf-8") as jsonl:
        for source_id, test_doc, answers_doc in doc_pairs(conn):
            blocks, pages_parsed, entries_total = answer_blocks_for_doc(conn, answers_doc)
            items, choice_map = question_items_for_doc(conn, test_doc)
            matched, unmatched, orphans = align_pair(items, blocks)

            inconsistent = 0
            for m in matched:
                consistent = 1
                if m.correct_choice:
                    letters = {c.split(")")[0].strip() for c in choice_map.get(m.item_id, [])}
                    consistent = 1 if (not letters or m.correct_choice in letters) else 0
                    inconsistent += 0 if consistent else 1
                conn.execute(
                    "INSERT OR REPLACE INTO qa_alignment VALUES (?,?,?,?,?,?,?,?,?)",
                    (m.item_id, answers_doc, m.answer_block, m.correct_choice,
                     m.answer_text, m.rationale[:400],
                     json.dumps(list(m.answer_flags)), consistent, now),
                )
                item_row = conn.execute(
                    "SELECT * FROM question_items WHERE item_id=?", (m.item_id,)
                ).fetchone()
                cols = [d[0] for d in conn.execute(
                    "SELECT * FROM question_items LIMIT 0").description]
                record = dict(zip(cols, item_row))
                record["choices"] = json.loads(record["choices"] or "[]")
                record["flags"] = json.loads(record["flags"] or "[]")
                record.update({
                    "answers_doc": answers_doc, "answer_block": m.answer_block,
                    "correct_choice": m.correct_choice,
                    "answer_text": m.answer_text,
                    "answer_rationale": m.rationale[:400],
                    "answer_flags": list(m.answer_flags),
                    "answer_consistent": bool(consistent),
                })
                jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")

            match_rate = round(100 * len(matched) / max(1, len(items)))
            report.append({
                "source_id": source_id, "test_doc": test_doc,
                "answers_doc": answers_doc, "question_items": len(items),
                "answer_pages": pages_parsed, "answer_entries": entries_total,
                "matched": len(matched), "match_rate_pct": match_rate,
                "unmatched_questions": len(unmatched),
                "orphan_answers": orphans, "inconsistent": inconsistent,
            })
            total_matched += len(matched)
            total_unmatched += len(unmatched)
            total_orphans += orphans
            total_inconsistent += inconsistent
    conn.commit()

    with REPORT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(report[0].keys()))
        writer.writeheader()
        writer.writerows(report)

    print("=" * 78)
    print("PHASE 6 - ANSWER ALIGNMENT SUMMARY")
    print("=" * 78)
    print(f"\n{'test doc':<32} {'items':>6} {'entries':>8} {'matched':>8} "
          f"{'rate':>5} {'un-q':>5} {'orph-a':>7} {'incons':>7}")
    print("-" * 84)
    for r in report:
        print(f"{r['test_doc']:<32} {r['question_items']:>6} "
              f"{r['answer_entries']:>8} {r['matched']:>8} "
              f"{r['match_rate_pct']:>4}% {r['unmatched_questions']:>5} "
              f"{r['orphan_answers']:>7} {r['inconsistent']:>7}")
    print("-" * 84)
    print(f"{'TOTAL':<32} {'':>6} {'':>8} {total_matched:>8} {'':>5} "
          f"{total_unmatched:>5} {total_orphans:>7} {total_inconsistent:>7}")
    print(f"\nElapsed: {time.time() - started:.1f}s")
    print(f"Q/A records : {QA_JSONL.relative_to(PROJECT_ROOT)} ({total_matched} records)")
    print(f"Report      : {REPORT_CSV.relative_to(PROJECT_ROOT)}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
