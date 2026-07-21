# Changelog

All notable states of the SAT Question Bank Pipeline. Dates are 2026.

## qbank-v1.0.0 — 07-22 (tag)

First versioned dataset release: 1,523 items (1,075 public / 448
restricted, 368 with verified answers), two-tier validation gate,
SHA-256-checksummed artifacts. Built from commit `52bf5fe`.

## Phase history

| Phase | Commit | Delivered |
|-------|--------|-----------|
| 1–2 | `ba666da` | Source vetting registry (13 sources, evidence-backed) + provenance-led collection (robots fail-safe, SHA-256 ledger, idempotent re-runs, manual intake) |
| 2.1 | `8466a90` | Ledger bugfix (per-file provenance URLs) + orphan-file reconciliation |
| 3 | `0180d86` | 780 pages rendered; quality-card classification & routing; Flask review dashboard; first 23 tests |
| 3.1 | `0287604` | Dashboard PORT env + autoPort launch config |
| 4 | `fe3ce29` | Tesseract OCR over 119 image-routed pages with per-page confidence (23,358 words recovered) |
| 5 | `710b073` | Question segmentation into a structured item bank (standalone-number layout support; /questions browser) |
| 6 | `52bf5fe` | Answer alignment via monotone windowed matching (382 matches, 0 consistency failures); classifier false-positive fix + `--reclassify` |
| 7 | `6c48b65` | Validated, versioned release builder (license partitions, manifest, quarantine policy) |
| 8 | — | Code freeze: handover guide, changelog, final presentation |

Full engineering narratives per phase: `docs/phaseN_README.md`.
