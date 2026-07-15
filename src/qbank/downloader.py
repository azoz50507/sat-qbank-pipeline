"""Collection downloader (Phase 2).

Fetches every collectible source from the Phase 1 registry into
``data/raw/<source_id>/`` and records full provenance (source, URL,
retrieval timestamp, SHA-256, size, content type, validation result)
in a ``collection_ledger`` table inside the registry database, plus a
CSV export for reporting.

Design rules:
- Only sources with status ``approved`` or ``conditional`` are considered;
  ``conditional`` sources additionally require recorded owner sign-off in
  the seed file, and their folders get a RESTRICTED_README.txt marker.
- robots.txt is fetched and honored per host. If robots.txt cannot be
  retrieved, the host is treated as off-limits for automation and the
  source is routed to the manual-intake path.
- Every downloaded payload is validated: magic-byte file-type check,
  HTML error/placeholder page rejection, minimum-size threshold.
- Idempotent: re-runs verify existing files against the ledger SHA-256
  and skip re-downloading; corrupted/missing files are re-fetched.

Usage:
    python src/qbank/downloader.py            # collect all eligible sources
    python src/qbank/downloader.py --intake   # ledger manually downloaded files
                                              # placed in data/raw/_inbox/<source_id>/
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.robotparser import RobotFileParser

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DIR = PROJECT_ROOT / "data" / "registry"
SEED_PATH = REGISTRY_DIR / "seed_sources.json"
DB_PATH = REGISTRY_DIR / "sources.db"
LEDGER_CSV = REGISTRY_DIR / "collection_ledger.csv"
RAW_DIR = PROJECT_ROOT / "data" / "raw"
INBOX_DIR = RAW_DIR / "_inbox"

USER_AGENT = (
    "sat-qbank-pipeline/0.1 (educational research; respects robots.txt; "
    "contact: fhdkbeer@gmail.com)"
)
TIMEOUT_S = 60
MIN_SIZE_BYTES = 10_000        # anything smaller is almost certainly an error page
POLITE_DELAY_S = 2.0           # pause between requests to the same host
MAX_RETRIES = 3

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS collection_ledger (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id        TEXT NOT NULL,
    url              TEXT NOT NULL,
    filename         TEXT,
    local_path       TEXT,
    sha256           TEXT,
    size_bytes       INTEGER,
    content_type     TEXT,
    detected_type    TEXT,
    usage_tag        TEXT,
    status           TEXT NOT NULL,  -- collected / skipped / failed / blocked_robots / manual_intake
    detail           TEXT,
    retrieved_at     TEXT,
    last_verified_at TEXT,
    UNIQUE (source_id, url)
);
"""

LEDGER_CSV_COLUMNS = [
    "source_id", "filename", "status", "usage_tag", "sha256", "size_bytes",
    "detected_type", "content_type", "url", "local_path", "retrieved_at",
    "last_verified_at", "detail",
]

RESTRICTED_README = """RESTRICTED MATERIAL - INTERNAL USE ONLY
=========================================
The files in this folder are copyright College Board, all rights reserved.
They were downloaded from College Board's official website for personal,
non-commercial educational use, with project-owner sign-off recorded in
data/registry/seed_sources.json (usage_tag: RESTRICTED_INTERNAL_USE_ONLY_DO_NOT_REDISTRIBUTE).

DO NOT redistribute these files or any questions extracted from them.
DO NOT publish pipeline outputs derived from these files.
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------

def http_get(url: str, timeout: int = TIMEOUT_S) -> tuple[bytes, str]:
    """GET a URL with our UA. Returns (body, content_type). Raises on failure."""
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as err:
            if err.code in (403, 404, 410):
                raise  # no point retrying
            last_err = err
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            last_err = err
        if attempt < MAX_RETRIES:
            time.sleep(5 * attempt)
    raise RuntimeError(f"GET failed after {MAX_RETRIES} attempts: {url} ({last_err})")


class RobotsGate:
    """Per-host robots.txt cache. Unreachable robots.txt => no automated access."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[RobotFileParser | None, str]] = {}

    def check(self, url: str) -> tuple[bool, str]:
        host = urllib.parse.urlsplit(url).netloc
        if host not in self._cache:
            robots_url = f"https://{host}/robots.txt"
            try:
                body, _ = http_get(robots_url, timeout=30)
                parser = RobotFileParser()
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
                self._cache[host] = (parser, "robots.txt fetched and parsed")
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    self._cache[host] = (None, "no robots.txt (404): allowed")
                else:
                    self._cache[host] = (None, f"robots.txt HTTP {err.code}: treating host as closed to automation")
            except Exception as err:  # noqa: BLE001 - any fetch failure closes the host
                self._cache[host] = (None, f"robots.txt unreachable ({type(err).__name__}): treating host as closed to automation")

        parser, note = self._cache[host]
        if parser is None:
            allowed = note.endswith("allowed")
            return allowed, note
        return parser.can_fetch(USER_AGENT, url), note


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def detect_type(first_bytes: bytes) -> str:
    head = first_bytes[:1024].lstrip()
    if head.startswith(b"%PDF-"):
        return "pdf"
    lowered = head[:512].lower()
    if lowered.startswith(b"<!doctype") or lowered.startswith(b"<html") or b"<html" in lowered:
        return "html"
    if head.startswith(b"{") or head.startswith(b"["):
        return "json"
    return "unknown"


def validate_payload(body: bytes, expected: str = "pdf") -> tuple[bool, str, str]:
    """Returns (ok, detected_type, detail)."""
    detected = detect_type(body)
    if detected == "html":
        return False, detected, "rejected: HTML page received where a document was expected (error/placeholder page)"
    if len(body) < MIN_SIZE_BYTES:
        return False, detected, f"rejected: payload too small ({len(body)} bytes < {MIN_SIZE_BYTES})"
    if expected == "pdf" and detected != "pdf":
        return False, detected, f"rejected: expected PDF magic bytes, got '{detected}'"
    return True, detected, "ok: magic-bytes and size checks passed"


def sha256_bytes(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_filename(name: str) -> str:
    name = urllib.parse.unquote(name)
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


# --------------------------------------------------------------------------
# Per-source file resolution
# --------------------------------------------------------------------------

@dataclass
class PlannedFile:
    url: str
    filename: str


def resolve_direct(source: dict) -> list[PlannedFile]:
    return [
        PlannedFile(url=u, filename=safe_filename(u.rsplit("/", 1)[-1]))
        for u in source.get("file_urls", [])
    ]


def resolve_archive_org(item_id: str) -> list[PlannedFile]:
    """Pick the best PDF derivative via the archive.org metadata API."""
    meta_url = f"https://archive.org/metadata/{item_id}"
    body, _ = http_get(meta_url)
    meta = json.loads(body)
    pdfs = [f for f in meta.get("files", []) if f.get("name", "").lower().endswith(".pdf")]
    if not pdfs:
        raise RuntimeError(f"no PDF derivative found for archive.org item {item_id}")
    # Prefer the canonical 'Text PDF' derivative; otherwise take the largest PDF.
    preferred = [f for f in pdfs if f.get("format") == "Text PDF"]
    chosen = preferred[0] if preferred else max(pdfs, key=lambda f: int(f.get("size", 0) or 0))
    name = chosen["name"]
    url = f"https://archive.org/download/{item_id}/{urllib.parse.quote(name)}"
    return [PlannedFile(url=url, filename=safe_filename(name))]


def resolve_collegeboard(page_url: str) -> list[PlannedFile]:
    """Enumerate practice-test PDF links from the official downloads page."""
    body, _ = http_get(page_url)
    html = body.decode("utf-8", errors="replace")
    hrefs = set(re.findall(r'href="([^"]+?\.pdf)"', html, flags=re.IGNORECASE))
    planned: list[PlannedFile] = []
    for href in sorted(hrefs):
        absolute = urllib.parse.urljoin(page_url, href)
        name = safe_filename(absolute.rsplit("/", 1)[-1])
        if "practice-test" in name.lower():
            planned.append(PlannedFile(url=absolute, filename=name))
    if not planned:
        raise RuntimeError("no practice-test PDF links found on the College Board page")
    return planned


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------

def open_ledger() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(LEDGER_SCHEMA)
    return conn


def ledger_upsert(conn: sqlite3.Connection, **row) -> None:
    conn.execute(
        """
        INSERT INTO collection_ledger
            (source_id, url, filename, local_path, sha256, size_bytes,
             content_type, detected_type, usage_tag, status, detail,
             retrieved_at, last_verified_at)
        VALUES (:source_id, :url, :filename, :local_path, :sha256, :size_bytes,
                :content_type, :detected_type, :usage_tag, :status, :detail,
                :retrieved_at, :last_verified_at)
        ON CONFLICT (source_id, url) DO UPDATE SET
            filename=excluded.filename, local_path=excluded.local_path,
            sha256=excluded.sha256, size_bytes=excluded.size_bytes,
            content_type=excluded.content_type, detected_type=excluded.detected_type,
            usage_tag=excluded.usage_tag, status=excluded.status,
            detail=excluded.detail, retrieved_at=excluded.retrieved_at,
            last_verified_at=excluded.last_verified_at
        """,
        row,
    )
    conn.commit()


def already_collected(conn: sqlite3.Connection, source_id: str, url: str) -> sqlite3.Row | None:
    """Return the existing ledger row if the file is present and its hash matches."""
    row = conn.execute(
        "SELECT * FROM collection_ledger WHERE source_id=? AND url=?",
        (source_id, url),
    ).fetchone()
    if not row or row["status"] not in ("collected", "manual_intake"):
        return None
    path = Path(row["local_path"]) if row["local_path"] else None
    if not path or not path.exists():
        return None
    if sha256_file(path) != row["sha256"]:
        log(f"    WARNING: checksum mismatch on disk for {path.name}; will re-download")
        return None
    conn.execute(
        "UPDATE collection_ledger SET last_verified_at=? WHERE id=?",
        (utc_now(), row["id"]),
    )
    conn.commit()
    return row


def export_ledger_csv(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT * FROM collection_ledger ORDER BY source_id, filename"
    ).fetchall()
    with LEDGER_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=LEDGER_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row[col] for col in LEDGER_CSV_COLUMNS})
    return len(rows)


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------

def collectible_sources(seed: dict) -> list[dict]:
    return [s for s in seed["sources"] if s["status"] in ("approved", "conditional")]


def collect_source(conn: sqlite3.Connection, gate: RobotsGate, source: dict) -> None:
    sid = source["id"]
    tag = source.get("usage_tag", "DO_NOT_COLLECT")
    plan = source.get("collection", {})
    method = plan.get("method", "skip")
    log(f"\n[{sid}]  status={source['status']}  tag={tag}")

    if method == "skip":
        ledger_upsert(
            conn, source_id=sid, url=source.get("landing_url", "n/a"),
            filename=None, local_path=None, sha256=None, size_bytes=None,
            content_type=None, detected_type=None, usage_tag=tag,
            status="skipped", detail=plan.get("reason", "skipped by collection plan"),
            retrieved_at=None, last_verified_at=utc_now(),
        )
        log(f"    skipped: {plan.get('reason', 'by plan')}")
        return

    if source["status"] == "conditional" and not plan.get("owner_signoff"):
        log("    BLOCKED: conditional source without recorded owner sign-off")
        return

    # Resolve the concrete file list.
    try:
        if method == "direct":
            planned = resolve_direct(source)
        elif method == "archive_org":
            planned = resolve_archive_org(plan["item_id"])
        elif method == "collegeboard_pdfs":
            page_url = plan["page_url"]
            allowed, note = gate.check(page_url)
            if not allowed:
                raise PermissionError(f"robots gate: {note}")
            planned = resolve_collegeboard(page_url)
        else:
            raise ValueError(f"unknown collection method: {method}")
    except Exception as err:  # noqa: BLE001 - any resolution failure routes to manual intake
        detail = f"resolution failed ({err}); route to manual intake: place files in data/raw/_inbox/{sid}/ and run --intake"
        ledger_upsert(
            conn, source_id=sid, url=source.get("landing_url", "n/a"),
            filename=None, local_path=None, sha256=None, size_bytes=None,
            content_type=None, detected_type=None, usage_tag=tag,
            status="blocked_robots" if isinstance(err, PermissionError) else "failed",
            detail=detail, retrieved_at=None, last_verified_at=utc_now(),
        )
        log(f"    {detail}")
        return

    dest_dir = RAW_DIR / sid
    dest_dir.mkdir(parents=True, exist_ok=True)
    if tag.startswith("RESTRICTED"):
        (dest_dir / "RESTRICTED_README.txt").write_text(RESTRICTED_README, encoding="utf-8")

    for pf in planned:
        if already_collected(conn, sid, pf.url):
            log(f"    ok (already collected, checksum verified): {pf.filename}")
            continue

        allowed, note = gate.check(pf.url)
        if not allowed:
            ledger_upsert(
                conn, source_id=sid, url=pf.url, filename=pf.filename,
                local_path=None, sha256=None, size_bytes=None, content_type=None,
                detected_type=None, usage_tag=tag, status="blocked_robots",
                detail=note, retrieved_at=None, last_verified_at=utc_now(),
            )
            log(f"    blocked by robots gate: {pf.filename} ({note})")
            continue

        log(f"    downloading: {pf.url}")
        try:
            body, content_type = http_get(pf.url)
        except Exception as err:  # noqa: BLE001
            ledger_upsert(
                conn, source_id=sid, url=pf.url, filename=pf.filename,
                local_path=None, sha256=None, size_bytes=None,
                content_type=None, detected_type=None, usage_tag=tag,
                status="failed", detail=f"download failed: {err}",
                retrieved_at=None, last_verified_at=utc_now(),
            )
            log(f"    FAILED: {err}")
            continue

        ok, detected, detail = validate_payload(body, expected="pdf")
        if not ok:
            ledger_upsert(
                conn, source_id=sid, url=pf.url, filename=pf.filename,
                local_path=None, sha256=sha256_bytes(body), size_bytes=len(body),
                content_type=content_type, detected_type=detected, usage_tag=tag,
                status="failed", detail=detail, retrieved_at=utc_now(),
                last_verified_at=utc_now(),
            )
            log(f"    REJECTED: {detail}")
            continue

        dest = dest_dir / pf.filename
        dest.write_bytes(body)
        digest = sha256_bytes(body)
        now = utc_now()
        ledger_upsert(
            conn, source_id=sid, url=pf.url, filename=pf.filename,
            local_path=str(dest.relative_to(PROJECT_ROOT)), sha256=digest,
            size_bytes=len(body), content_type=content_type, detected_type=detected,
            usage_tag=tag, status="collected", detail=detail,
            retrieved_at=now, last_verified_at=now,
        )
        log(f"    collected: {pf.filename} ({len(body):,} bytes, sha256={digest[:16]}...)")
        time.sleep(POLITE_DELAY_S)


def run_intake(conn: sqlite3.Connection, seed: dict) -> None:
    """Ledger files manually downloaded by the project owner.

    Expected layout: data/raw/_inbox/<source_id>/<files>. Each file is
    validated, hashed, moved into data/raw/<source_id>/ and recorded with
    status 'manual_intake' (provenance URL = source landing page).
    """
    by_id = {s["id"]: s for s in collectible_sources(seed)}
    if not INBOX_DIR.exists():
        log(f"No inbox directory found ({INBOX_DIR.relative_to(PROJECT_ROOT)}); nothing to intake.")
        return
    moved = 0
    for src_dir in sorted(p for p in INBOX_DIR.iterdir() if p.is_dir()):
        source = by_id.get(src_dir.name)
        if not source:
            log(f"  WARNING: inbox folder '{src_dir.name}' is not an approved/conditional source id; ignored")
            continue
        tag = source.get("usage_tag", "DO_NOT_COLLECT")
        dest_dir = RAW_DIR / src_dir.name
        dest_dir.mkdir(parents=True, exist_ok=True)
        if tag.startswith("RESTRICTED"):
            (dest_dir / "RESTRICTED_README.txt").write_text(RESTRICTED_README, encoding="utf-8")
        for file in sorted(p for p in src_dir.iterdir() if p.is_file()):
            if file.suffix.lower() != ".pdf":
                continue  # instructions/readme files live in the inbox too
            body = file.read_bytes()
            ok, detected, detail = validate_payload(body, expected="pdf")
            if not ok:
                log(f"  REJECTED {src_dir.name}/{file.name}: {detail}")
                continue
            dest = dest_dir / safe_filename(file.name)
            shutil.move(str(file), dest)
            now = utc_now()
            ledger_upsert(
                conn, source_id=src_dir.name,
                # the fragment keeps (source_id, url) unique per file: manual
                # downloads all share one landing page as their provenance URL
                url=f"manual-download:{source.get('landing_url', 'n/a')}#{dest.name}",
                filename=dest.name, local_path=str(dest.relative_to(PROJECT_ROOT)),
                sha256=sha256_file(dest), size_bytes=dest.stat().st_size,
                content_type="application/pdf (manual intake)", detected_type=detected,
                usage_tag=tag, status="manual_intake",
                detail=f"manually downloaded by project owner from {source.get('landing_url')}; validated on intake",
                retrieved_at=now, last_verified_at=now,
            )
            moved += 1
            log(f"  intake ok: {src_dir.name}/{dest.name}")
    log(f"\nIntake complete: {moved} file(s) ledgered.")
    reconcile_untracked(conn, by_id)


def reconcile_untracked(conn: sqlite3.Connection, by_id: dict[str, dict]) -> None:
    """Adopt files that were placed directly into source folders.

    Provenance safety net: if a human bypasses the inbox and drops files
    straight into ``data/raw/<source_id>/``, those files exist on disk with
    no ledger entry - and everything downstream works off the ledger. This
    pass finds such orphans, validates and hashes them, and records them
    with an explicit 'adopted by reconciliation' detail so the audit trail
    stays honest about how they arrived.
    """
    adopted = 0
    for source_id, source in by_id.items():
        src_dir = RAW_DIR / source_id
        if not src_dir.exists():
            continue
        known = {
            row["local_path"]
            for row in conn.execute(
                "SELECT local_path FROM collection_ledger WHERE local_path IS NOT NULL"
            )
        }
        tag = source.get("usage_tag", "DO_NOT_COLLECT")
        for file in sorted(src_dir.glob("*.pdf")):
            rel = str(file.relative_to(PROJECT_ROOT))
            if rel in known:
                continue
            body = file.read_bytes()
            ok, detected, detail = validate_payload(body, expected="pdf")
            if not ok:
                log(f"  RECONCILE REJECTED {source_id}/{file.name}: {detail}")
                continue
            now = utc_now()
            ledger_upsert(
                conn, source_id=source_id,
                url=f"manual-download:{source.get('landing_url', 'n/a')}#{file.name}",
                filename=file.name, local_path=rel,
                sha256=sha256_file(file), size_bytes=file.stat().st_size,
                content_type="application/pdf (reconciled)", detected_type=detected,
                usage_tag=tag, status="manual_intake",
                detail=(
                    "adopted by reconciliation: file was placed directly in the "
                    f"source folder (bypassing _inbox); validated and hashed on {now}"
                ),
                retrieved_at=now, last_verified_at=now,
            )
            adopted += 1
            log(f"  reconciled: {source_id}/{file.name}")
    if adopted:
        log(f"Reconciliation: adopted {adopted} orphan file(s) into the ledger.")


def print_summary(conn: sqlite3.Connection) -> None:
    print("\n" + "=" * 62)
    print("PHASE 2 - COLLECTION SUMMARY")
    print("=" * 62)
    rows = conn.execute(
        """SELECT status, COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes
           FROM collection_ledger GROUP BY status ORDER BY status"""
    ).fetchall()
    print(f"\n{'status':<16} {'files':>5} {'total size':>12}")
    print("-" * 36)
    for row in rows:
        print(f"{row['status']:<16} {row['n']:>5} {row['bytes']:>12,}")

    print(f"\n{'source':<36} {'file':<44} {'size':>10}  sha256(12)")
    print("-" * 110)
    for row in conn.execute(
        """SELECT source_id, filename, size_bytes, sha256 FROM collection_ledger
           WHERE status IN ('collected', 'manual_intake') ORDER BY source_id"""
    ):
        sha = (row["sha256"] or "")[:12]
        size = f"{row['size_bytes']:,}" if row["size_bytes"] else "-"
        print(f"{row['source_id']:<36} {(row['filename'] or '-'):<44} {size:>10}  {sha}")


def main(argv: list[str]) -> int:
    seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    conn = open_ledger()
    try:
        if "--intake" in argv:
            run_intake(conn, seed)
        else:
            gate = RobotsGate()
            sources = collectible_sources(seed)
            log(f"Collectible sources (approved/conditional): {len(sources)}")
            for source in sources:
                collect_source(conn, gate, source)
        count = export_ledger_csv(conn)
        print_summary(conn)
        print(f"\nLedger DB  : {DB_PATH.relative_to(PROJECT_ROOT)} (table collection_ledger)")
        print(f"Ledger CSV : {LEDGER_CSV.relative_to(PROJECT_ROOT)} ({count} rows)")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
