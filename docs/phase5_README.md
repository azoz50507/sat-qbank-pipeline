# Phase 5 — Question Segmentation

**Status: complete** · Extraction date: 2026-07-15

## Goal

Turn routed pages into a **question bank**: split every `content` page into
structured question items with a documented schema, explicit quality flags,
and full provenance back to the exact page image each item came from.

## Question-item schema

Stored in the `question_items` table and `data/qbank/question_items.jsonl`
(one JSON object per line):

| Field | Meaning |
|-------|---------|
| `item_id` | `source:doc:pNNNN:seq` — globally unique, provenance-readable |
| `number_label` | the number as printed (`13`, `IV`) |
| `kind` | `multiple_choice` / `free_response` (Ans.___ blanks) / `unknown` (essay/computation) |
| `stem` | question text (wrapped lines joined) |
| `choices` | `A) …` list; wrapped choice lines merged |
| `flags` | structural warnings (`short_stem`, `truncated_at_page_end`, `has_subparts`, `roman_numbered`, `inline_choices`, `lonely_choice`) |
| `status` | `ok` / `needs_review` (any risky flag, or OCR source below 70 confidence) |
| `extraction_source` | `text_layer` or `ocr` (+ `ocr_mean_conf`) |
| `usage_tag` | inherited from the source — RESTRICTED items must stay local |

## How segmentation works (`src/qbank/segmenter.py` — pure, unit-tested)

Text selection per page (`extract.py`): text-routed pages use the embedded
layer; image-routed pages use Phase 4 OCR text only when its quality flag is
good/fair; the rest are skipped with a recorded reason.

Detection heuristics, each guarded against known false positives:

1. **Inline numbers** `7.` / `7)` / `7,` (1–3 digits, so years never match;
   the comma variant absorbs a common OCR error).
2. **Standalone numbers** (College Board's layout puts the number on its own
   line): counts as a start **only** when followed by a real text line
   (≥15 chars, not a choice, not another number) — bare page numbers and
   module labels have nothing qualifying after them.
3. **Roman numerals** (`IV.`) only with a substantial stem (old CEEB essay
   numbering).
4. **Choices** `A)`–`E)` with wrapped-line joining → `multiple_choice`;
   lowercase `(a)` sub-parts stay in the stem.
5. **`Ans.____` blanks** (1926 style) → `free_response`.
6. **Noise filtering**: dotted/dashed separator rules are dropped before any
   other rule sees them.

## Results

| Metric | Value |
|--------|------:|
| Content pages segmented | 428 of 456 (28 skipped: OCR empty/review) |
| **Question items extracted** | **1,477** |
| multiple_choice | 377 (College Board: 376 of 481 items) |
| free_response | 4 (1926 SAT `Ans.___` style) |
| unknown (essay/computation) | 1,096 (correct for the historical volumes) |
| status ok | 1,310 (89%) |
| needs_review | 167 (11%) — every one carries its reason |

Extraction runs in **0.2 s** (pure text processing over prepared assets).

### The bug the run exposed (and the fix)

The first extraction produced only **1 item from 184 College Board pages** —
the segmenter assumed `N. text` inline numbering, but College Board's
digital PDFs put the question number **alone on its own line**. Inspecting a
real page led to the standalone-number rule with its next-line guard, and
counts jumped 753 → 1,477 with all 50 tests still green. A second bug was
caught by the test suite itself before ever running: the `Ans.` blank
pattern matched the prefix of the word "Answer" (fixed with a word
boundary).

## Review dashboard

`/questions` — filterable question-bank browser (source / kind / status)
showing each item's stem, choices, flags, extraction source + confidence,
a restricted badge where applicable, and a link to its source page image.
The overview gained a "question items extracted" tile.

## Known limitations (v1, by design)

- Items are segmented **per page**: a question continuing onto the next page
  is flagged `truncated_at_page_end`, not merged across pages yet.
- OCR-garbled numbers (`Tl.` for `11.`) are not recovered; affected items on
  the 1926 SAT are simply missed. OCR post-correction is future work.
- Math formulas inside old-scan stems remain garbled (inherited Phase 4
  limitation); those items carry OCR confidence for downstream filtering.
- `(a)/(b)` sub-parts are kept inside one item (`has_subparts` flag), not
  split into separate items.

## Reproducing

```
python src/qbank/extract.py    # rebuilds the question bank (fast, idempotent)
python -m pytest               # 50 tests
python src/qbank/dashboard.py  # browse /questions
```

`data/qbank/` is gitignored: it contains question text derived from
RESTRICTED sources and is fully regenerable from the pipeline.
