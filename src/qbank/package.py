"""Dataset packaging (Phase 7).

Builds a versioned question-bank release from the pipeline's outputs:

    data/release/qbank-v<VERSION>/
    ├── manifest.json      build metadata: version, git commit, counts,
    │                      SHA-256 checksums of every artifact
    ├── STATS.md           human-readable statistics report
    ├── stats.json         the same numbers, machine-readable
    ├── SCHEMA.md          record schema documentation
    ├── public/            PUBLIC_DOMAIN / CC-licensed items - shareable
    │   ├── questions.jsonl
    │   └── README.md
    └── restricted/        College Board-derived items - INTERNAL ONLY
        ├── questions.jsonl
        └── RESTRICTED_README.txt

A validation gate runs first: structural errors (missing fields, malformed
choices, inconsistent answers, broken provenance) FAIL the build; quality
warnings (needs_review items, truncation flags) are reported and counted
but do not block. Records merge each item with its aligned answer.

Usage:
    python src/qbank/package.py
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "registry" / "sources.db"
RELEASE_ROOT = PROJECT_ROOT / "data" / "release"

VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"
KINDS = {"multiple_choice", "free_response", "unknown"}
STATUSES = {"ok", "needs_review"}
PUBLIC_TAGS = {"PUBLIC_DOMAIN", "CC_BY_SA_ATTRIBUTION_SHAREALIKE"}
RESTRICTED_PREFIX = "RESTRICTED"

RESTRICTED_NOTE = """RESTRICTED PARTITION - INTERNAL USE ONLY
==========================================
Question items in this partition are derived from College Board practice
materials (copyright College Board, all rights reserved). They exist for
personal, non-commercial educational use within this training project.

DO NOT redistribute this partition, publish it, commit it to any
repository, or use it to train models for external release.
"""


# --------------------------------------------------------------------------
# Validation gate (pure - unit-tested)
# --------------------------------------------------------------------------

def validate_item(record: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for one merged question record."""
    errors: list[str] = []
    warnings: list[str] = []

    for field in ("item_id", "source_id", "doc", "kind", "status", "usage_tag"):
        if not record.get(field):
            errors.append(f"missing required field: {field}")
    if not isinstance(record.get("page_num"), int) or record.get("page_num", 0) < 1:
        errors.append("page_num must be a positive integer")
    if record.get("kind") not in KINDS:
        errors.append(f"unknown kind: {record.get('kind')!r}")
    if record.get("status") not in STATUSES:
        errors.append(f"unknown status: {record.get('status')!r}")

    stem = (record.get("stem") or "").strip()
    if not stem:
        warnings.append("empty stem")

    choices = record.get("choices") or []
    if record.get("kind") == "multiple_choice":
        if len(choices) < 2:
            errors.append(f"multiple_choice with {len(choices)} choice(s)")
        letters = [c.split(")")[0].strip() for c in choices]
        if len(set(letters)) != len(letters):
            errors.append("duplicate choice letters")

    answer = record.get("answer")
    if answer and answer.get("correct_choice"):
        letters = {c.split(")")[0].strip() for c in choices}
        if letters and answer["correct_choice"] not in letters:
            errors.append(
                f"answer letter {answer['correct_choice']} not among choices")

    tag = record.get("usage_tag", "")
    if tag not in PUBLIC_TAGS and not tag.startswith(RESTRICTED_PREFIX):
        errors.append(f"unknown usage tag: {tag!r}")

    if record.get("status") == "needs_review":
        warnings.append("needs_review")
    for flag in record.get("flags") or []:
        if flag == "truncated_at_page_end":
            warnings.append("truncated_at_page_end")
    return errors, warnings


def partition_for(record: dict) -> str:
    return "restricted" if record["usage_tag"].startswith(RESTRICTED_PREFIX) else "public"


# Content-shape defects quarantine the single item (excluded from the
# release, reported); anything else is a pipeline-integrity failure and
# fails the whole build.
QUARANTINE_MARKERS = ("choice(s)", "duplicate choice letters", "answer letter")


def is_quarantinable(errors: list[str]) -> bool:
    return bool(errors) and all(
        any(marker in error for marker in QUARANTINE_MARKERS)
        for error in errors
    )


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=10)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_records(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    has_qa = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='qa_alignment'"
    ).fetchone()
    records = []
    for row in conn.execute(
        "SELECT * FROM question_items ORDER BY source_id, doc, page_num, item_seq"
    ):
        record = {
            "item_id": row["item_id"], "source_id": row["source_id"],
            "doc": row["doc"], "page_num": row["page_num"],
            "item_seq": row["item_seq"], "number_label": row["number_label"],
            "kind": row["kind"], "stem": row["stem"],
            "choices": json.loads(row["choices"] or "[]"),
            "flags": json.loads(row["flags"] or "[]"),
            "status": row["status"],
            "extraction_source": row["extraction_source"],
            "ocr_mean_conf": row["ocr_mean_conf"],
            "usage_tag": row["usage_tag"],
            "page_image": f"data/pages/{row['source_id']}/{row['doc']}/page_{row['page_num']:04d}.png",
            "answer": None,
        }
        records.append(record)
    if has_qa:
        answers = {
            row["item_id"]: row
            for row in conn.execute("SELECT * FROM qa_alignment")
        }
        for record in records:
            row = answers.get(record["item_id"])
            if row:
                record["answer"] = {
                    "correct_choice": row["correct_choice"],
                    "answer_text": row["answer_text"],
                    "rationale": row["rationale"],
                    "block": row["answer_block"],
                    "answers_doc": row["answers_doc"],
                    "flags": json.loads(row["answer_flags"] or "[]"),
                    "consistent": bool(row["consistent"]),
                }
    return records


def compute_stats(records: list[dict]) -> dict:
    def count_by(key_fn) -> dict:
        out: dict[str, int] = {}
        for record in records:
            key = key_fn(record)
            out[key] = out.get(key, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    answered = [r for r in records if r["answer"]]
    return {
        "total_items": len(records),
        "by_partition": count_by(partition_for),
        "by_source": count_by(lambda r: r["source_id"]),
        "by_kind": count_by(lambda r: r["kind"]),
        "by_status": count_by(lambda r: r["status"]),
        "by_extraction_source": count_by(lambda r: r["extraction_source"]),
        "answered_items": len(answered),
        "answer_consistency_failures": sum(
            1 for r in answered if not r["answer"]["consistent"]),
        "answered_by_doc": dict(sorted(
            count_by(lambda r: r["doc"] if r["answer"] else "_unanswered").items())),
    }


def write_stats_md(stats: dict, path: Path, built_at: str, commit: str) -> None:
    lines = [
        f"# SAT QBank v{VERSION} - Statistics",
        f"\nBuilt {built_at} from commit `{commit}`.\n",
        f"**Total question items: {stats['total_items']}** "
        f"({stats['answered_items']} with aligned answers, "
        f"{stats['answer_consistency_failures']} consistency failures)\n",
    ]
    for title, key in (
        ("By partition", "by_partition"), ("By source", "by_source"),
        ("By kind", "by_kind"), ("By status", "by_status"),
        ("By extraction source", "by_extraction_source"),
    ):
        lines.append(f"\n## {title}\n")
        lines.append("| Value | Items |")
        lines.append("|-------|------:|")
        for value, count in stats[key].items():
            lines.append(f"| {value} | {count} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


SCHEMA_MD = f"""# SAT QBank Record Schema (v{SCHEMA_VERSION})

One JSON object per line (JSONL). Fields:

| Field | Type | Meaning |
|-------|------|---------|
| item_id | str | `source:doc:pNNNN:seq` - unique, provenance-readable |
| source_id | str | registry source (see data/registry/source_registry.csv) |
| doc | str | source document (PDF stem) |
| page_num | int | 1-based page in the document |
| item_seq | int | reading-order position on the page |
| number_label | str | question number as printed ("13", "IV") |
| kind | str | multiple_choice / free_response / unknown |
| stem | str | question text |
| choices | list[str] | "A) ..." entries (empty unless multiple_choice) |
| flags | list[str] | structural warnings from segmentation |
| status | str | ok / needs_review |
| extraction_source | str | text_layer / ocr |
| ocr_mean_conf | float? | mean OCR word confidence (ocr items only) |
| usage_tag | str | licensing tier - PUBLIC_DOMAIN, CC_*, RESTRICTED_* |
| page_image | str | repo-relative path to the page render (provenance) |
| answer | obj? | aligned answer, when available |

`answer` object: `correct_choice` (A-D), `answer_text` (SPR answers),
`rationale` (explanation excerpt), `block` (module, e.g. RW1),
`answers_doc`, `flags`, `consistent` (letter verified among choices).

Partitions: `public/` (public-domain / CC sources) and `restricted/`
(College Board-derived - internal use only, never redistribute).
"""


def main() -> int:
    started = time.time()
    conn = sqlite3.connect(DB_PATH)
    records = load_records(conn)
    conn.close()

    # ---- validation gate --------------------------------------------------
    fatal_count = 0
    warning_counts: dict[str, int] = {}
    included: list[dict] = []
    excluded: list[dict] = []
    for record in records:
        errors, warnings = validate_item(record)
        for message in warnings:
            warning_counts[message] = warning_counts.get(message, 0) + 1
        if errors:
            if is_quarantinable(errors):
                record["_exclusion_reasons"] = errors
                excluded.append(record)
                continue
            for message in errors:
                print(f"FATAL  {record.get('item_id', '?')}: {message}")
                fatal_count += 1
            continue
        included.append(record)
    if fatal_count:
        print(f"\nBUILD FAILED: {fatal_count} pipeline-integrity error(s).")
        return 1
    records = included

    # ---- write release ----------------------------------------------------
    release_dir = RELEASE_ROOT / f"qbank-v{VERSION}"
    built_at = utc_now()
    commit = git_commit()
    artifacts: dict[str, Path] = {}

    partitions: dict[str, list[dict]] = {"public": [], "restricted": []}
    for record in records:
        partitions[partition_for(record)].append(record)

    for name, part_records in partitions.items():
        part_dir = release_dir / name
        part_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = part_dir / "questions.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for record in part_records:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        artifacts[f"{name}/questions.jsonl"] = jsonl_path

    (release_dir / "public" / "README.md").write_text(
        f"# SAT QBank v{VERSION} - public partition\n\n"
        "Question items derived exclusively from US public-domain sources "
        "(the 1926 SAT and CEEB examination volumes, published before 1931) "
        "and CC-licensed material. See ../SCHEMA.md for the record format "
        "and ../manifest.json for provenance and checksums.\n",
        encoding="utf-8")
    (release_dir / "restricted" / "RESTRICTED_README.txt").write_text(
        RESTRICTED_NOTE, encoding="utf-8")

    if excluded:
        excluded_path = release_dir / "excluded_items.jsonl"
        with excluded_path.open("w", encoding="utf-8") as fh:
            for record in excluded:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        artifacts["excluded_items.jsonl"] = excluded_path

    stats = compute_stats(records)
    stats["excluded_items"] = len(excluded)
    stats["validation_warnings"] = dict(
        sorted(warning_counts.items(), key=lambda kv: -kv[1]))
    stats_json = release_dir / "stats.json"
    stats_json.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    artifacts["stats.json"] = stats_json

    stats_md = release_dir / "STATS.md"
    write_stats_md(stats, stats_md, built_at, commit)
    artifacts["STATS.md"] = stats_md

    schema_md = release_dir / "SCHEMA.md"
    schema_md.write_text(SCHEMA_MD, encoding="utf-8")
    artifacts["SCHEMA.md"] = schema_md

    manifest = {
        "name": "sat-qbank",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "built_at": built_at,
        "git_commit": commit,
        "pipeline_phases": 7,
        "counts": {
            "total_items": stats["total_items"],
            "public_items": len(partitions["public"]),
            "restricted_items": len(partitions["restricted"]),
            "answered_items": stats["answered_items"],
            "excluded_items": len(excluded),
        },
        "validation": {
            "fatal_errors": 0,
            "quarantined": len(excluded),
            "warnings": stats["validation_warnings"],
        },
        "artifacts": {
            rel: {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for rel, path in sorted(artifacts.items())
        },
        "usage_note": (
            "public/ may be shared with attribution where required; "
            "restricted/ is internal-only College Board-derived material."
        ),
    }
    (release_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    # ---- summary ----------------------------------------------------------
    print("=" * 62)
    print(f"PHASE 7 - RELEASE BUILD: qbank-v{VERSION}")
    print("=" * 62)
    print(f"\nValidation: 0 fatal, {len(excluded)} quarantined "
          f"(see excluded_items.jsonl), warnings: {stats['validation_warnings']}")
    print(f"\n{'partition':<12} {'items':>6} {'answered':>9}")
    print("-" * 32)
    for name, part_records in partitions.items():
        answered = sum(1 for r in part_records if r["answer"])
        print(f"{name:<12} {len(part_records):>6} {answered:>9}")
    print(f"\nRelease dir : {release_dir.relative_to(PROJECT_ROOT)}")
    print(f"Git commit  : {commit}   Built: {built_at}")
    print(f"Elapsed: {time.time() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
