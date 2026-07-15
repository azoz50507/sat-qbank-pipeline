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
│       └── downloader.py      <- Phase 2: collector + provenance ledger
├── data/
│   ├── registry/
│   │   ├── seed_sources.json  <- curated source list + license evidence
│   │   ├── sources.db         <- SQLite: sources + collection_ledger (generated)
│   │   ├── source_registry.csv<- flat export for reports (generated)
│   │   └── collection_ledger.csv <- per-file provenance export (generated)
│   └── raw/                   <- downloaded originals, one folder per source
│       └── _inbox/            <- drop zone for manual-intake files
└── docs/
    ├── phase1_README.md       <- Phase 1 documentation
    ├── phase2_README.md       <- Phase 2 documentation
    └── evidence/
        └── phase1_license_evidence.md
```

## Phases

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Source discovery & licensing vetting -> source registry | **Done** |
| 2 | Collection: downloader + provenance ledger + integrity checks | **Done** |
| 3 | Rendering & routing: PDF -> page images + text layer, page classification + review dashboard | Pending |

## Quickstart

```
python src/qbank/registry.py     # Phase 1: rebuild the vetted source registry
python src/qbank/downloader.py   # Phase 2: collect eligible sources (idempotent)
python src/qbank/downloader.py --intake   # ledger manually downloaded files
```

Python 3.10+; Phases 1–2 use only the standard library. Full write-ups:
[docs/phase1_README.md](docs/phase1_README.md) ·
[docs/phase2_README.md](docs/phase2_README.md).
