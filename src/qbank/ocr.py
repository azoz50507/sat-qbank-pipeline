"""OCR pass for image-routed pages (Phase 4).

Every page the Phase 3 router sent to the image path (missing or garbled
text layer) is re-rendered at OCR_DPI grayscale straight from the source
PDF and run through Tesseract. For each page we store:

- the recovered text  -> ``data/pages/<source>/<doc>/page_NNNN.ocr.txt``
- an ``ocr_results`` row: engine + version, word count, mean word
  confidence (from Tesseract's TSV output), and a quality flag
  (good / fair / review / empty) so weak pages surface for human review.

Idempotent: pages with an existing result row and text file are skipped;
``--force`` re-runs everything. Quality summary is exported to
``data/pages/ocr_quality.csv``.

Usage:
    python src/qbank/ocr.py [--force]
"""

from __future__ import annotations

import csv
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "registry" / "sources.db"
PAGES_DIR = PROJECT_ROOT / "data" / "pages"
QUALITY_CSV = PAGES_DIR / "ocr_quality.csv"

OCR_DPI = 300           # Tesseract's sweet spot for old book scans
PSM = 3                 # fully automatic page segmentation
LANG = "eng"
GOOD_CONF = 80.0        # mean word confidence thresholds
FAIR_CONF = 60.0

OCR_SCHEMA = """
CREATE TABLE IF NOT EXISTS ocr_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      TEXT NOT NULL,
    doc            TEXT NOT NULL,
    page_num       INTEGER NOT NULL,
    engine         TEXT NOT NULL,
    engine_version TEXT,
    dpi            INTEGER,
    psm            INTEGER,
    word_count     INTEGER,
    mean_conf      REAL,
    text_chars     INTEGER,
    quality_flag   TEXT,    -- good / fair / review / empty
    ocr_path       TEXT,
    created_at     TEXT,
    UNIQUE (source_id, doc, page_num)
);
"""


def find_tesseract() -> str:
    exe = shutil.which("tesseract")
    if exe:
        return exe
    default = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if default.exists():
        return str(default)
    raise SystemExit(
        "Tesseract not found. Install it (Windows: winget install "
        "UB-Mannheim.TesseractOCR) and re-run."
    )


# --------------------------------------------------------------------------
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class TsvStats:
    word_count: int
    mean_conf: float


def parse_tsv(tsv_text: str) -> TsvStats:
    """Word count and mean confidence from Tesseract TSV output.

    Word rows have level == 5; rows with conf == -1 are layout containers,
    and whitespace-only text cells are noise - both are excluded.
    """
    confs: list[float] = []
    lines = tsv_text.splitlines()
    for line in lines[1:]:  # skip header
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        try:
            level, conf = int(cols[0]), float(cols[10])
        except ValueError:
            continue
        if level == 5 and conf >= 0 and cols[11].strip():
            confs.append(conf)
    if not confs:
        return TsvStats(word_count=0, mean_conf=0.0)
    return TsvStats(word_count=len(confs), mean_conf=sum(confs) / len(confs))


def quality_flag(stats: TsvStats) -> str:
    if stats.word_count == 0:
        return "empty"
    if stats.mean_conf >= GOOD_CONF:
        return "good"
    if stats.mean_conf >= FAIR_CONF:
        return "fair"
    return "review"


# --------------------------------------------------------------------------
# OCR run
# --------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def engine_version(exe: str) -> str:
    out = subprocess.run([exe, "--version"], capture_output=True, text=True)
    first = (out.stdout or out.stderr).splitlines()[0]
    return first.strip()


def eligible_pages(conn: sqlite3.Connection) -> dict[tuple[str, str], list[int]]:
    """Image-routed pages grouped by (source_id, doc)."""
    grouped: dict[tuple[str, str], list[int]] = {}
    for source_id, doc, page_num in conn.execute(
        "SELECT source_id, doc, page_num FROM pages WHERE route='image' "
        "ORDER BY source_id, doc, page_num"
    ):
        grouped.setdefault((source_id, doc), []).append(page_num)
    return grouped


def pdf_paths_by_stem(conn: sqlite3.Connection) -> dict[tuple[str, str], Path]:
    mapping = {}
    for source_id, filename, local_path in conn.execute(
        "SELECT source_id, filename, local_path FROM collection_ledger "
        "WHERE local_path IS NOT NULL"
    ):
        mapping[(source_id, Path(filename).stem)] = PROJECT_ROOT / local_path
    return mapping


def already_done(conn: sqlite3.Connection, source_id: str, doc: str, num: int) -> bool:
    row = conn.execute(
        "SELECT ocr_path FROM ocr_results WHERE source_id=? AND doc=? AND page_num=?",
        (source_id, doc, num),
    ).fetchone()
    return bool(row and (PROJECT_ROOT / row[0]).exists())


def ocr_page(exe: str, page: pymupdf.Page, tmp: Path) -> tuple[str, str]:
    """Render one page at OCR_DPI and run Tesseract. Returns (text, tsv)."""
    img = tmp / "page.png"
    out_base = tmp / "out"
    page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY, alpha=False).save(img)
    result = subprocess.run(
        [exe, str(img), str(out_base), "-l", LANG, "--dpi", str(OCR_DPI),
         "--psm", str(PSM), "txt", "tsv"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"tesseract failed: {result.stderr.strip()[:200]}")
    text = (out_base.with_suffix(".txt")).read_text(encoding="utf-8", errors="replace")
    tsv = (out_base.with_suffix(".tsv")).read_text(encoding="utf-8", errors="replace")
    return text, tsv


def export_quality_csv(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT * FROM ocr_results ORDER BY mean_conf ASC"
    ).fetchall()
    cols = ["source_id", "doc", "page_num", "quality_flag", "mean_conf",
            "word_count", "text_chars", "engine", "engine_version", "dpi",
            "psm", "ocr_path", "created_at"]
    with QUALITY_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row[c] for c in cols})
    return len(rows)


def print_summary(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 62)
    print("PHASE 4 - OCR SUMMARY")
    print("=" * 62)
    total, mean_all = conn.execute(
        "SELECT COUNT(*), ROUND(AVG(mean_conf), 1) FROM ocr_results"
    ).fetchone()
    print(f"\nPages OCR'd: {total}   corpus mean confidence: {mean_all}")

    print(f"\n{'quality':<10} {'pages':>6}   (good >=80, fair >=60, review <60)")
    print("-" * 48)
    for flag, n in conn.execute(
        "SELECT quality_flag, COUNT(*) FROM ocr_results GROUP BY quality_flag "
        "ORDER BY COUNT(*) DESC"
    ):
        print(f"{flag:<10} {n:>6}")

    print(f"\n{'source':<36} {'pages':>6} {'mean conf':>10} {'words':>8}")
    print("-" * 66)
    for row in conn.execute(
        """SELECT source_id, COUNT(*), ROUND(AVG(mean_conf),1), SUM(word_count)
           FROM ocr_results GROUP BY source_id ORDER BY source_id"""
    ):
        print(f"{row[0]:<36} {row[1]:>6} {row[2]:>10} {row[3]:>8,}")

    print("\nLowest-confidence pages (for human review):")
    for row in conn.execute(
        """SELECT source_id, doc, page_num, mean_conf, word_count
           FROM ocr_results WHERE quality_flag != 'empty'
           ORDER BY mean_conf ASC LIMIT 5"""
    ):
        print(f"  {row[0]}/{row[1]} p.{row[2]:<4} conf={row[3]:.1f} words={row[4]}")


def main(argv: list[str]) -> int:
    force = "--force" in argv
    exe = find_tesseract()
    version = engine_version(exe)
    print(f"engine: {version}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(OCR_SCHEMA)

    grouped = eligible_pages(conn)
    pdfs = pdf_paths_by_stem(conn)
    total_pages = sum(len(v) for v in grouped.values())
    print(f"image-routed pages to OCR: {total_pages} across {len(grouped)} documents")

    started = time.time()
    done = skipped = 0
    with tempfile.TemporaryDirectory(prefix="qbank_ocr_") as tmpdir:
        tmp = Path(tmpdir)
        for (source_id, doc), page_nums in grouped.items():
            pdf_path = pdfs.get((source_id, doc))
            if not pdf_path or not pdf_path.exists():
                print(f"  MISSING PDF for {source_id}/{doc} - skipped")
                continue
            with pymupdf.open(pdf_path) as pdf:
                for num in page_nums:
                    if not force and already_done(conn, source_id, doc, num):
                        skipped += 1
                        continue
                    text, tsv = ocr_page(exe, pdf[num - 1], tmp)
                    stats = parse_tsv(tsv)
                    flag = quality_flag(stats)
                    ocr_rel = f"data/pages/{source_id}/{doc}/page_{num:04d}.ocr.txt"
                    (PROJECT_ROOT / ocr_rel).write_text(text, encoding="utf-8")
                    conn.execute(
                        """INSERT INTO ocr_results
                               (source_id, doc, page_num, engine, engine_version,
                                dpi, psm, word_count, mean_conf, text_chars,
                                quality_flag, ocr_path, created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT (source_id, doc, page_num) DO UPDATE SET
                                engine=excluded.engine,
                                engine_version=excluded.engine_version,
                                dpi=excluded.dpi, psm=excluded.psm,
                                word_count=excluded.word_count,
                                mean_conf=excluded.mean_conf,
                                text_chars=excluded.text_chars,
                                quality_flag=excluded.quality_flag,
                                ocr_path=excluded.ocr_path,
                                created_at=excluded.created_at""",
                        (source_id, doc, num, "tesseract", version, OCR_DPI,
                         PSM, stats.word_count, round(stats.mean_conf, 1),
                         len(text.strip()), flag, ocr_rel, utc_now()),
                    )
                    done += 1
            conn.commit()
            print(f"  [{source_id}/{doc}] ocr done={done} skipped={skipped}")

    count = export_quality_csv(conn)
    print_summary(conn)
    print(f"\nElapsed: {time.time() - started:.1f}s")
    print(f"Quality CSV : {QUALITY_CSV.relative_to(PROJECT_ROOT)} ({count} rows)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
