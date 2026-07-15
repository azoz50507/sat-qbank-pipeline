# SAT Question Bank Extraction Pipeline

A pipeline that discovers, vets, collects, and processes openly licensed /
public-domain SAT-style practice materials into a structured question bank.
Built as a phased engineering project with an auditable trail at every step:
every source has recorded license evidence, every file has provenance and a
checksum, and every processing decision is logged.

## Guiding principle

**Ethical collection only.** A source enters the pipeline only after its
license or terms have been verified and recorded. Free-to-download does not
mean openly licensed — the registry distinguishes the two explicitly.
robots.txt is respected during collection.

## Project structure

```
sat-qbank-pipeline/
├── README.md                  <- this file
├── requirements.txt
├── src/
│   └── qbank/
│       ├── __init__.py
│       ├── registry.py        <- Phase 1: source registry builder
│       ├── downloader.py      <- Phase 2: collector + provenance ledger
│       ├── pagestats.py       <- Phase 3: page quality stats + routing rules
│       ├── render.py          <- Phase 3: PDF -> images/text + classification
│       └── dashboard.py       <- Phase 3: local review dashboard (Flask)
├── tests/                     <- pytest suite (validation + routing rules)
├── data/
│   ├── registry/
│   │   ├── seed_sources.json  <- curated source list + license evidence
│   │   ├── sources.db         <- SQLite: sources, collection_ledger, pages
│   │   ├── source_registry.csv<- flat export for reports (generated)
│   │   └── collection_ledger.csv <- per-file provenance export (generated)
│   ├── raw/                   <- downloaded originals, one folder per source
│   │   └── _inbox/            <- drop zone for manual-intake files
│   └── pages/                 <- rendered page PNGs, thumbs, text layers,
│                                 page_index.csv, routing_log.jsonl
└── docs/
    ├── phase1_README.md       <- Phase 1 documentation
    ├── phase2_README.md       <- Phase 2 documentation
    ├── phase3_README.md       <- Phase 3 documentation
    └── evidence/
        └── phase1_license_evidence.md
```

## Phases

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Source discovery & licensing vetting -> source registry | **Done** |
| 2 | Collection: downloader + provenance ledger + integrity checks | **Done** |
| 3 | Rendering & routing: page images + text layer, quality cards, classification, review dashboard, tests | **Done** |

## Quickstart

```
pip install -r requirements.txt
python src/qbank/registry.py              # Phase 1: rebuild the vetted source registry
python src/qbank/downloader.py            # Phase 2: collect eligible sources (idempotent)
python src/qbank/downloader.py --intake   # ledger manually downloaded files
python src/qbank/render.py                # Phase 3: render + classify + route all pages
python -m pytest                          # run the test suite
python src/qbank/dashboard.py             # review dashboard -> http://127.0.0.1:8765
```

Python 3.10+. Full write-ups:
[docs/phase1_README.md](docs/phase1_README.md) ·
[docs/phase2_README.md](docs/phase2_README.md) ·
[docs/phase3_README.md](docs/phase3_README.md).

## Running on a fresh machine

```
git clone https://github.com/azoz50507/sat-qbank-pipeline.git
cd sat-qbank-pipeline
pip install -r requirements.txt
python src/qbank/downloader.py    # re-fetches all public-domain sources (checksum-verified)
python src/qbank/render.py        # renders, classifies, and routes every page
python -m pytest                  # 23 tests
python src/qbank/dashboard.py     # review dashboard -> http://127.0.0.1:8765
```

Raw PDFs and rendered page images are intentionally **not** committed:

- **Public-domain sources** (the 1926 SAT and CEEB volumes) are re-downloaded
  automatically by the downloader, with SHA-256 verification against the
  committed provenance ledger.
- **College Board practice tests** are copyright-restricted and cannot be
  redistributed. Each user downloads them personally in a browser following
  `data/raw/_inbox/collegeboard-paper-practice-tests/HOW_TO_DOWNLOAD.txt`,
  then runs `python src/qbank/downloader.py --intake`.
