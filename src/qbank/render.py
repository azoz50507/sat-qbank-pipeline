"""Rendering & routing driver (Phase 3).

For every PDF in the collection ledger (status ``collected`` or
``manual_intake``), this module:

1. renders each page to a PNG at RENDER_DPI -> ``data/pages/<source>/<doc>/page_NNNN.png``
2. renders a small grayscale thumbnail (also reused to measure ink density)
3. extracts the embedded text layer -> ``page_NNNN.txt``
4. computes :class:`qbank.pagestats.PageStats`, classifies the page, and
   routes it to the text or image extraction path
5. records everything in the ``pages`` table (SQLite), a CSV export, and an
   append-only JSONL routing log

Idempotent: pages already present in the DB with their rendered files on
disk are skipped; use ``--force`` to re-render everything.

Usage:
    python src/qbank/render.py [--force]
"""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qbank.pagestats import PageStats, classify_page, orientation  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "registry" / "sources.db"
PAGES_DIR = PROJECT_ROOT / "data" / "pages"
PAGE_INDEX_CSV = PAGES_DIR / "page_index.csv"
ROUTING_LOG = PAGES_DIR / "routing_log.jsonl"

RENDER_DPI = 150          # archival page image
THUMB_DPI = 40            # dashboard thumbnail + ink measurement
INK_THRESHOLD = 200       # gray value below which a pixel counts as "ink"
CENTER_MARGIN = 0.05      # crop 5% margins before measuring ink (scan edges)

PAGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      TEXT NOT NULL,
    doc            TEXT NOT NULL,
    page_num       INTEGER NOT NULL,
    width_pt       REAL,
    height_pt      REAL,
    orientation    TEXT,
    text_chars     INTEGER,
    word_count     INTEGER,
    alnum_ratio    REAL,
    ink_ratio      REAL,
    classification TEXT NOT NULL,
    route          TEXT NOT NULL,
    reason         TEXT,
    image_path     TEXT,
    thumb_path     TEXT,
    text_path      TEXT,
    usage_tag      TEXT,
    rendered_at    TEXT,
    UNIQUE (source_id, doc, page_num)
);
"""

CSV_COLUMNS = [
    "source_id", "doc", "page_num", "classification", "route", "reason",
    "text_chars", "word_count", "alnum_ratio", "ink_ratio", "orientation",
    "usage_tag", "image_path", "thumb_path", "text_path", "rendered_at",
]

# bytes.translate table: gray value -> 1 if ink, else 0 (C-speed counting)
_INK_TABLE = bytes(1 if value < INK_THRESHOLD else 0 for value in range(256))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ink_ratio_center(pix: pymupdf.Pixmap) -> float:
    """Dark-pixel fraction of the central region of a grayscale pixmap.

    Archive scans often have black edges from the scanning bed; measuring
    only the central 90% keeps those artifacts from inflating the density.
    """
    width, height, stride = pix.width, pix.height, pix.stride
    x0, x1 = int(width * CENTER_MARGIN), int(width * (1 - CENTER_MARGIN))
    y0, y1 = int(height * CENTER_MARGIN), int(height * (1 - CENTER_MARGIN))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    flags = pix.samples.translate(_INK_TABLE)
    ink = sum(
        flags.count(1, row * stride + x0, row * stride + x1)
        for row in range(y0, y1)
    )
    return ink / ((y1 - y0) * (x1 - x0))


def text_stats(text: str) -> tuple[int, int, float]:
    stripped = text.strip()
    compact = "".join(stripped.split())
    alnum = sum(1 for ch in compact if ch.isalnum())
    ratio = alnum / len(compact) if compact else 0.0
    return len(stripped), len(stripped.split()), ratio


def ledgered_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT source_id, filename, local_path, usage_tag
           FROM collection_ledger
           WHERE status IN ('collected', 'manual_intake') AND local_path IS NOT NULL
           ORDER BY source_id, filename"""
    ).fetchall()


def page_done(conn: sqlite3.Connection, source_id: str, doc: str, num: int) -> bool:
    row = conn.execute(
        "SELECT image_path, text_path FROM pages WHERE source_id=? AND doc=? AND page_num=?",
        (source_id, doc, num),
    ).fetchone()
    if not row:
        return False
    return all((PROJECT_ROOT / row[key]).exists() for key in ("image_path", "text_path"))


def process_document(
    conn: sqlite3.Connection, source_id: str, pdf_path: Path,
    usage_tag: str, force: bool, log_fh,
) -> tuple[int, int]:
    """Render/route one PDF. Returns (pages_processed, pages_skipped)."""
    doc_name = pdf_path.stem
    out_dir = PAGES_DIR / source_id / doc_name
    out_dir.mkdir(parents=True, exist_ok=True)

    processed = skipped = 0
    with pymupdf.open(pdf_path) as doc:
        page_count = doc.page_count
        for index in range(page_count):
            num = index + 1
            if not force and page_done(conn, source_id, doc_name, num):
                skipped += 1
                continue

            page = doc[index]
            image_rel = f"data/pages/{source_id}/{doc_name}/page_{num:04d}.png"
            thumb_rel = f"data/pages/{source_id}/{doc_name}/thumb_{num:04d}.png"
            text_rel = f"data/pages/{source_id}/{doc_name}/page_{num:04d}.txt"

            page.get_pixmap(dpi=RENDER_DPI).save(PROJECT_ROOT / image_rel)
            thumb = page.get_pixmap(dpi=THUMB_DPI, colorspace=pymupdf.csGRAY, alpha=False)
            thumb.save(PROJECT_ROOT / thumb_rel)

            text = page.get_text("text")
            (PROJECT_ROOT / text_rel).write_text(text, encoding="utf-8")

            chars, words, alnum = text_stats(text)
            stats = PageStats(
                page_num=num, doc_page_count=page_count,
                width_pt=page.rect.width, height_pt=page.rect.height,
                text_chars=chars, word_count=words, alnum_ratio=round(alnum, 4),
                ink_ratio=round(ink_ratio_center(thumb), 5),
                head_text=text.strip()[:600],
            )
            decision = classify_page(stats)
            now = utc_now()

            conn.execute(
                """INSERT INTO pages
                       (source_id, doc, page_num, width_pt, height_pt, orientation,
                        text_chars, word_count, alnum_ratio, ink_ratio,
                        classification, route, reason, image_path, thumb_path,
                        text_path, usage_tag, rendered_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT (source_id, doc, page_num) DO UPDATE SET
                        width_pt=excluded.width_pt, height_pt=excluded.height_pt,
                        orientation=excluded.orientation, text_chars=excluded.text_chars,
                        word_count=excluded.word_count, alnum_ratio=excluded.alnum_ratio,
                        ink_ratio=excluded.ink_ratio, classification=excluded.classification,
                        route=excluded.route, reason=excluded.reason,
                        image_path=excluded.image_path, thumb_path=excluded.thumb_path,
                        text_path=excluded.text_path, usage_tag=excluded.usage_tag,
                        rendered_at=excluded.rendered_at""",
                (
                    source_id, doc_name, num, stats.width_pt, stats.height_pt,
                    orientation(stats), stats.text_chars, stats.word_count,
                    stats.alnum_ratio, stats.ink_ratio, decision.classification,
                    decision.route, decision.reason, image_rel, thumb_rel,
                    text_rel, usage_tag, now,
                ),
            )
            log_fh.write(json.dumps({
                "ts": now, "source_id": source_id, "doc": doc_name, "page": num,
                "classification": decision.classification, "route": decision.route,
                "reason": decision.reason,
                "stats": {
                    "text_chars": stats.text_chars, "word_count": stats.word_count,
                    "alnum_ratio": stats.alnum_ratio, "ink_ratio": stats.ink_ratio,
                    "orientation": orientation(stats),
                },
            }) + "\n")
            processed += 1
        conn.commit()
    return processed, skipped


def export_csv(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT * FROM pages ORDER BY source_id, doc, page_num"
    ).fetchall()
    with PAGE_INDEX_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row[col] for col in CSV_COLUMNS})
    return len(rows)


def print_summary(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 66)
    print("PHASE 3 - RENDERING & ROUTING SUMMARY")
    print("=" * 66)

    total = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    print(f"\nTotal pages rendered & routed: {total}")

    print(f"\n{'classification':<16} {'pages':>6}    {'route':<8} {'pages':>6}")
    print("-" * 48)
    by_class = conn.execute(
        "SELECT classification, COUNT(*) FROM pages GROUP BY classification ORDER BY 2 DESC"
    ).fetchall()
    by_route = conn.execute(
        "SELECT route, COUNT(*) FROM pages GROUP BY route ORDER BY 2 DESC"
    ).fetchall()
    for i in range(max(len(by_class), len(by_route))):
        left = f"{by_class[i][0]:<16} {by_class[i][1]:>6}" if i < len(by_class) else " " * 23
        right = f"{by_route[i][0]:<8} {by_route[i][1]:>6}" if i < len(by_route) else ""
        print(f"{left}    {right}")

    print(f"\n{'source':<36} {'pages':>6} {'content':>8} {'answer':>7} {'cover':>6} {'index':>6} {'blank':>6}")
    print("-" * 84)
    for row in conn.execute(
        """SELECT source_id, COUNT(*) AS n,
                  SUM(classification='content') AS c,
                  SUM(classification='answer_key') AS a,
                  SUM(classification='cover') AS v,
                  SUM(classification='index') AS i,
                  SUM(classification='blank') AS b
           FROM pages GROUP BY source_id ORDER BY source_id"""
    ):
        print(f"{row[0]:<36} {row[1]:>6} {row[2]:>8} {row[3]:>7} {row[4]:>6} {row[5]:>6} {row[6]:>6}")


def main(argv: list[str]) -> int:
    force = "--force" in argv
    PAGES_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(PAGES_SCHEMA)

    started = time.time()
    docs = ledgered_documents(conn)
    print(f"Documents in ledger to render: {len(docs)}")

    with ROUTING_LOG.open("a", encoding="utf-8") as log_fh:
        for row in docs:
            pdf_path = PROJECT_ROOT / row["local_path"]
            if not pdf_path.exists():
                print(f"  MISSING on disk (skipped): {row['local_path']}")
                continue
            processed, skipped = process_document(
                conn, row["source_id"], pdf_path, row["usage_tag"], force, log_fh
            )
            label = f"[{row['source_id']}/{pdf_path.stem}]"
            print(f"  {label:<70} rendered={processed:<4} skipped={skipped}")

    count = export_csv(conn)
    print_summary(conn)
    elapsed = time.time() - started
    print(f"\nElapsed: {elapsed:.1f}s")
    print(f"Page index CSV : {PAGE_INDEX_CSV.relative_to(PROJECT_ROOT)} ({count} rows)")
    print(f"Routing log    : {ROUTING_LOG.relative_to(PROJECT_ROOT)}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
