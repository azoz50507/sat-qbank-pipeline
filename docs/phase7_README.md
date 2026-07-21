# Phase 7 — Dataset Packaging

**Status: complete** · Release: `qbank-v1.0.0` · Built 2026-07-22 from commit `52bf5fe`

## Goal

Turn pipeline outputs into a **versioned, validated, self-describing
dataset release** — something a successor can pick up cold: partitioned by
license, checksummed, statistically summarized, and schema-documented.

## Release layout (`data/release/qbank-v1.0.0/`)

```
manifest.json          version, git commit, build time, counts,
                       SHA-256 + size of every artifact
STATS.md / stats.json  full statistics (human + machine readable)
SCHEMA.md              record format documentation
excluded_items.jsonl   quarantined items with their exclusion reasons
public/                1,075 items from public-domain / CC sources
    questions.jsonl    - shareable (attribution where required)
restricted/            448 College Board-derived items - INTERNAL ONLY
    questions.jsonl    368 of them carry aligned, verified answers
    RESTRICTED_README.txt
```

## The validation gate

`package.py` refuses to ship what it cannot vouch for. Two severity tiers:

| Tier | Examples | Consequence |
|------|----------|-------------|
| **Fatal** (pipeline integrity) | missing item_id, unknown kind/status/tag, bad page number | **build fails** |
| **Quarantine** (content shape) | multiple-choice with <2 choices, duplicate choice letters, answer letter not among choices | item excluded, written to `excluded_items.jsonl` with reasons |
| Warning (quality) | needs_review status, truncation flags, empty stems | counted in manifest, item ships |

First build: **0 fatal, 18 quarantined** (choice-gluing artifacts from
figure-heavy pages — 14 of them had aligned answers, which is why the
release carries 368 answered records vs Phase 6's 382 matches), warnings
recorded (182 needs_review, 149 truncation flags, 7 empty stems).

## Result: qbank-v1.0.0

| Metric | Value |
|--------|------:|
| Items in release | **1,523** (of 1,541 in the bank; 18 quarantined) |
| public partition | 1,075 |
| restricted partition | 448 |
| Answered records (restricted) | 368, all consistency-verified |
| Artifacts checksummed | 6 (SHA-256 in manifest) |
| Build time | 0.1 s, fully reproducible |

## Design notes

- **License-partitioned by construction**: the `usage_tag` recorded in
  Phase 1 travels through every stage and finally decides each item's
  partition — the legal decision made at source-vetting time enforces
  itself at release time.
- **Provenance closes the loop**: manifest carries the git commit; every
  record carries its `page_image` path; every artifact carries a SHA-256 —
  the same checksum discipline the collection ledger started in Phase 2.
- **`data/release/` is gitignored** (restricted partition inside;
  rebuildable with one command). Publishing the public partition somewhere
  citable is a possible follow-up, at the project owner's discretion.

## Reproducing

```
python src/qbank/package.py    # validates, then builds data/release/qbank-v1.0.0/
python -m pytest               # 80 tests
```
