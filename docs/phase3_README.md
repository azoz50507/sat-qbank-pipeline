# Phase 3 — Rendering & Routing

**Status: complete** · Processing date: 2026-07-15

## Goal

Turn every collected PDF into per-page assets ready for extraction: a page
image, the embedded text layer, and a measured **quality card** that drives
an automatic classification (content / answer_key / cover / index / blank)
and an extraction **route** (text path / image-OCR path / skip) — every
decision logged and reviewable in a local dashboard.

## Architecture

```
collection_ledger (Phase 2)
        |
        v
src/qbank/render.py ---- renders 150-DPI page PNG + 40-DPI gray thumbnail
        |                extracts embedded text layer -> .txt
        |                measures the page  -------------+
        v                                                |
src/qbank/pagestats.py   <- pure logic, no I/O ----------+
        |    PageStats -> classify_page() -> Decision(classification, route, reason)
        v
pages table (SQLite) + data/pages/page_index.csv + routing_log.jsonl
        |
        v
src/qbank/dashboard.py   <- Flask review UI on 127.0.0.1:8765
```

### Quality card measurements (per page)

| Measurement | How | Used for |
|-------------|-----|----------|
| `text_chars`, `word_count` | embedded text layer via PyMuPDF | blank/cover/content thresholds |
| `alnum_ratio` | alphanumeric share of non-space chars | detecting garbled OCR layers |
| `ink_ratio` | dark-pixel share of the **central 90%** of a grayscale render (scan-edge artifacts excluded), counted at C speed via `bytes.translate` | blank detection; catching scanned content with no text layer |
| `orientation` | page box aspect | downstream layout handling |
| header patterns | regex over the top 600 chars | answer_key / index detection |

### Classification & routing rules (`pagestats.py`)

Ordered rules, each with an explicit reason string that lands in the DB, the
JSONL log, and the dashboard:

1. no text + no ink → **blank** (skip)
2. answer/scoring header pattern → **answer_key** (text or image route)
3. TOC/index header pattern + word cap → **index** (skip)
4. first two pages + sparse text → **cover** (skip)
5. substantial text → **content**; thin text but real ink → **content**
   (scanned page)
6. otherwise → **blank** ("no test material" dividers)

Content-bearing pages route to **text** only if the layer is usable
(≥200 chars and alnum ratio ≥0.55); otherwise **image** (OCR needed).
All thresholds are module constants — tunable and unit-tested.

## Results (2026-07-15 corpus)

**780 pages** across 17 documents rendered & routed in 312 s.

| Classification | Pages | | Route | Pages |
|---------------|------:|-|-------|------:|
| content | 456 | | text | 577 (74%) |
| answer_key | 240 | | image/OCR | 119 |
| blank | 72 | | skip | 84 |
| cover | 9 | | | |
| index | 3 | | | |

| Source | Pages | Content | Answer | Cover | Index | Blank |
|--------|------:|--------:|-------:|------:|------:|------:|
| ceeb-history-1901-1905 | 77 | 61 | 0 | 1 | 0 | 15 |
| ceeb-history-c1915 | 56 | 44 | 0 | 2 | 1 | 9 |
| ceeb-math-1911-1915 | 72 | 60 | 0 | 2 | 1 | 9 |
| ceeb-math-1916-1920 | 108 | 88 | 11 | 2 | 1 | 6 |
| collegeboard-paper-practice-tests | 445 | 184 | 229 | 0 | 0 | 32 |
| sat-1926-original | 22 | 19 | 0 | 2 | 0 | 1 |

Notable validations:
- The 1926 SAT scan has **no text layer at all** — pages measured ~0 chars
  but ink ≈ 0.08 and were correctly classified content → image/OCR route.
- The CEEB 1916–1920 math volume's answers section was picked up by the
  header patterns (11 answer_key pages) with no source-specific rules.
- College Board answer/scoring documents route almost entirely to the text
  path (born-digital PDFs with clean text layers).

## Review dashboard

```
python src/qbank/dashboard.py      # http://127.0.0.1:8765
```

- Stat tiles (pages, content, answer-key, route shares)
- Per-source classification distribution bars
- Filterable, paginated thumbnail grid (source / classification / route)
- Per-page quality card: full render, all measurements, the routing reason,
  and the extracted text layer side by side
- Pages from RESTRICTED sources carry a warning badge and banner; the app
  binds to localhost only

## Tests

```
python -m pytest        # 23 tests
```

`tests/test_pagestats.py` covers every classification rule, both routing
directions, threshold boundaries, and orientation; 
`tests/test_downloader_validation.py` covers magic-byte detection, error-page
rejection, size gates, and filename hygiene from Phase 2.

## Reproducing

```
python src/qbank/render.py           # idempotent; --force to re-render
python -m pytest
python src/qbank/dashboard.py
```

## Known limitations

- Classification thresholds were tuned on this corpus; a new source family
  (e.g. landscape-heavy or non-English material) may need re-tuning — the
  dashboard exists precisely to catch that quickly.
- `index` detection is conservative (3 hits) — old CEEB volumes label their
  TOC sparsely; misses fall through to `content`, which is the safe direction
  (nothing is lost, extraction just sees a low-value page).
- The image/OCR route is a *routing target* only for now; actual OCR is a
  Phase 4 concern.
