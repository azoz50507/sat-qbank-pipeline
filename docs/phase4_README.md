# Phase 4 — OCR for Image-Routed Pages

**Status: complete** · OCR date: 2026-07-15 · Engine: Tesseract 5.4.0 (eng)

## Goal

Recover text from every page the Phase 3 router sent to the **image path** —
pages whose embedded text layer is missing (the 1926 SAT scan) or garbled
(older Google/Archive scans) — and attach a measurable quality score to each
result so weak pages surface for human review instead of silently polluting
the question bank.

## How it works (`src/qbank/ocr.py`)

1. Selects the 119 `route='image'` pages from the `pages` table and joins
   them back to their source PDFs through the collection ledger.
2. Re-renders each page **at 300 DPI grayscale directly from the source
   PDF** (not the 150-DPI archive PNG) — Tesseract's accuracy sweet spot.
3. Runs Tesseract with `--psm 3`, producing both plain text and TSV output.
4. Parses word-level confidences from the TSV (container rows and
   whitespace cells excluded) into a mean confidence per page.
5. Flags each page: `good` (≥80), `fair` (≥60), `review` (<60),
   `empty` (no words found).
6. Stores text as `page_NNNN.ocr.txt` beside the page assets, metadata in
   the `ocr_results` table, and a sorted `data/pages/ocr_quality.csv`.

Idempotent like every other stage: existing results are skipped unless
`--force`. The dashboard shows an OCR panel (text + confidence + flag) on
every OCR'd page and a corpus tile on the overview.

## Results

119 pages OCR'd across 9 documents in 156 s. **23,358 words recovered.**

| Quality flag | Pages | Meaning |
|--------------|------:|---------|
| good | 74 | mean confidence ≥ 80 |
| fair | 17 | 60–79: usable, verify during extraction |
| review | 3 | < 60: route to human review |
| empty | 25 | no words — mostly blank-ish scans, stamps, plates |

| Source | Pages | Mean conf | Words recovered |
|--------|------:|----------:|----------------:|
| ceeb-history-1901-1905 | 60 | 66.9 | 12,143 |
| sat-1926-original | 19 | 75.7 | 9,831 |
| collegeboard-paper-practice-tests | 7 | 86.2 | 999 |
| ceeb-math-1916-1920 | 13 | 51.3 | 169 |
| ceeb-math-1911-1915 | 15 | 65.0 | 136 |
| ceeb-history-c1915 | 5 | 63.5 | 80 |

### Headline validation

The original **1926 SAT had zero embedded text** — Phase 3 detected its
pages as content by ink density alone. Phase 4 recovered **9,831 words** of
its questions at 75.7 mean confidence: the first machine-readable text this
pipeline has of the first SAT ever administered.

### Honest limitations (why confidence scoring matters)

- Century-old typography produces systematic errors ("eubie" for "cubic",
  "walter" for "water"); mean confidence quantifies exactly how much
  cleanup the extraction phase should expect per page.
- The two CEEB math volumes score lowest (51–65) with few words: their
  image-routed pages are dominated by **mathematical notation**, which
  Tesseract cannot read. Recovering formulas would need a math-aware OCR
  model — recorded as future work, out of Phase 4 scope.
- 25 "empty" pages confirm the router was conservative in the right
  direction: sending a near-blank scan to OCR costs seconds; losing a
  content page would have cost data.

## Reproducing

```
winget install UB-Mannheim.TesseractOCR   # system dependency (Windows)
python src/qbank/ocr.py                   # idempotent; --force to re-run
python -m pytest                          # includes 9 OCR unit tests
```

## Files

- `src/qbank/ocr.py` — OCR driver (pure helpers `parse_tsv` /
  `quality_flag` are unit-tested in `tests/test_ocr.py`)
- `data/pages/<source>/<doc>/page_NNNN.ocr.txt` — recovered text
- `data/pages/ocr_quality.csv` — per-page quality report, worst first
- `ocr_results` table in `data/registry/sources.db`
