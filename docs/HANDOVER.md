# Handover Guide — SAT Question Bank Pipeline

Written at code freeze (end of the 8-week training project, 2026-07-22,
tag `qbank-v1.0.0`). This is the document a successor reads first.

## What this project is

An end-to-end pipeline that turns openly licensed / public-domain SAT
practice material into a versioned, license-partitioned question bank,
with an auditable trail at every stage. Seven processing phases, each with
its own module, docs, and tests; a local review dashboard; 80 unit tests.

## One-command tour (fresh machine)

```
git clone https://github.com/azoz50507/sat-qbank-pipeline.git
cd sat-qbank-pipeline
pip install -r requirements.txt
winget install UB-Mannheim.TesseractOCR        # OCR engine (Windows)

python src/qbank/registry.py       # 1. rebuild the vetted source registry
python src/qbank/downloader.py     # 2. fetch public-domain sources (idempotent)
python src/qbank/render.py         # 3. render + classify + route all pages
python src/qbank/ocr.py            # 4. OCR the image-routed pages
python src/qbank/extract.py        # 5. segment content pages into items
python src/qbank/align.py          # 6. align answers -> Q/A records
python src/qbank/package.py        # 7. build data/release/qbank-v1.0.0/
python -m pytest                   # 80 tests
python src/qbank/dashboard.py      # review UI -> http://127.0.0.1:8765
```

College Board materials are optional and must be downloaded manually in a
browser (their CDN blocks automated clients) — see
`data/raw/_inbox/collegeboard-paper-practice-tests/HOW_TO_DOWNLOAD.txt`,
then `python src/qbank/downloader.py --intake`.

## Architecture map

| Stage | Module | Persists to |
|-------|--------|-------------|
| Source vetting | `registry.py` (+ `data/registry/seed_sources.json` = human-curated truth) | `sources` table, `source_registry.csv` |
| Collection | `downloader.py` | `collection_ledger` table, `data/raw/`, `collection_ledger.csv` |
| Render & route | `render.py` + `pagestats.py` (pure rules) | `pages` table, `data/pages/`, `routing_log.jsonl` |
| OCR | `ocr.py` | `ocr_results` table, `*.ocr.txt`, `ocr_quality.csv` |
| Segmentation | `extract.py` + `segmenter.py` (pure rules) | `question_items` table, `data/qbank/question_items.jsonl` |
| Answer alignment | `align.py` + `answers.py` (pure rules) | `qa_alignment` table, `data/qbank/qa_records.jsonl` |
| Packaging | `package.py` | `data/release/qbank-vX.Y.Z/` |

Everything lives in one SQLite DB: `data/registry/sources.db`.
Pure-logic modules (`pagestats`, `segmenter`, `answers`, and
`package.validate_item`) hold every heuristic and are fully unit-tested;
driver modules do I/O only.

## Load-bearing design rules (do not break these)

1. **The ledger is the source of truth.** Files on disk without a
   `collection_ledger` row are invisible downstream. `--intake` includes a
   reconciliation pass that adopts orphans.
2. **`usage_tag` flows from Phase 1 vetting to release partitioning.**
   RESTRICTED-tagged content never enters git (`data/raw`, `data/pages`,
   `data/qbank`, `data/release` are all gitignored) and never leaves the
   machine.
3. **Free-to-download is not openly licensed.** New sources go through the
   seed file with recorded evidence before any collection.
4. **After changing classification rules** run
   `python src/qbank/render.py --reclassify` (recomputes from stored
   measurements in seconds — no re-render), then re-run extract/align/
   package downstream.
5. **robots.txt fail-safe:** an unreachable robots.txt closes a host to
   automation. Do not "fix" this into default-allow.
6. **Alignment matcher:** monotone window (10) with confirmation-checked
   initial lock. A resync-widening variant was tried and measurably hurt
   (92 -> 79 on test 4) — the A/B story is in docs/phase6_README.md.

## Known limitations (= future work)

- Math-notation OCR: Tesseract cannot read formulas; CEEB math items carry
  low confidence. A math-aware model (e.g. pix2tex-class) is the next step.
- Cross-page questions are flagged `truncated_at_page_end`, not merged.
- `(a)/(b)` sub-parts stay inside one item (`has_subparts` flag).
- 18 items quarantined at packaging (choice-gluing on figure-heavy pages);
  reasons in the release's `excluded_items.jsonl`.
- ~20% of College Board paper-test questions lack aligned answers
  (segmentation recall on figure-heavy/cross-page layouts).
- Publishing the public partition (1,075 PD/CC items) somewhere citable is
  a decision for the project owner.

## Per-phase documentation

`docs/phase1_README.md` … `docs/phase7_README.md` (each: goal, method,
results, challenges), `docs/evidence/phase1_license_evidence.md`
(licensing evidence log), `CHANGELOG.md` (phase -> commit map).
