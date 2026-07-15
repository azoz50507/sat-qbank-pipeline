# Phase 2 — Collection

**Status: complete** · Collection date: 2026-07-15

## Goal

Fetch every collectible source from the Phase 1 registry into a structured
raw-data directory, with full per-file provenance (source, URL, retrieval
timestamp, SHA-256 checksum) in a ledger, and integrity checks that keep bad
payloads out of the pipeline.

## What was built

`src/qbank/downloader.py` — a zero-dependency (stdlib-only) collector with:

| Feature | Implementation |
|---------|----------------|
| Eligibility | Only `approved`/`conditional` registry sources; `conditional` additionally requires recorded owner sign-off in the seed file |
| robots.txt compliance | Fetched and parsed per host with a descriptive User-Agent; **an unreachable robots.txt closes the host to automation** (fail-safe default) |
| Politeness | Descriptive UA with contact address, 2 s delay between downloads, 3 retries with backoff on transient errors only |
| File resolution | Three strategies: `direct` URL; `archive_org` (best PDF derivative chosen via the archive.org metadata API, preferring the canonical "Text PDF"); `collegeboard_pdfs` (link enumeration from the official page) |
| Integrity checks | PDF magic-byte validation (`%PDF-`), HTML error/placeholder-page rejection, 10 KB minimum-size threshold |
| Provenance ledger | `collection_ledger` table in `data/registry/sources.db` + CSV export: URL, local path, SHA-256, size, content type, detected type, usage tag, status, timestamps |
| Idempotent re-runs | Re-runs verify each on-disk file against its ledger SHA-256 and skip re-downloading; missing or corrupted files are re-fetched automatically |
| Restricted-material tagging | Sources tagged `RESTRICTED_*` get a `RESTRICTED_README.txt` marker written into their raw-data folder |
| Manual intake | `--intake` mode ledgers files a human downloaded in a browser (for hosts that block automation): validates, hashes, moves from `data/raw/_inbox/<source_id>/` into place with status `manual_intake` |

## Results

| Metric | Value |
|--------|-------|
| Sources collected automatically | 5 / 7 eligible |
| Files downloaded | 5 PDFs, 14,527,512 bytes (~13.9 MB) |
| Validation failures | 0 (all payloads passed magic-byte + size checks) |
| Skipped by plan | 1 (Wikibooks — HTML wiki, no question content) |
| Routed to manual intake | 1 (College Board — host blocks non-browser clients) |
| Ledger rows | 7 (one per source/file decision, including skips and blocks) |

### Collected files

| Source | File | Size | SHA-256 (first 12) |
|--------|------|------|--------------------|
| sat-1926-original | Scholastic_Aptitude_Test__SAT__from_1926.pdf | 924,133 | fbf76fa07a1f |
| ceeb-math-1911-1915 | questmathematics00collrich.pdf | 3,545,439 | c5bb7f7be6f7 |
| ceeb-math-1916-1920 | mathematicsquest00collrich.pdf | 6,238,807 | d3c4c5f0cfd1 |
| ceeb-history-c1915 | questexamination00collrich.pdf | 2,100,642 | ca9ffe1f4f1a |
| ceeb-history-1901-1905 | examinationques01boargoog.pdf | 1,718,491 | f7630a91264a |

## The College Board path (conditional source)

Project-owner sign-off for internal educational use was recorded on
2026-07-15 in the seed file. Automated collection was then attempted and
correctly **not** forced through:

1. First run: the landing page was fetched (robots.txt permitted it), but the
   PDF links are rendered client-side by JavaScript — zero links in the HTML.
2. Direct probes of the known PDF URLs were reset at the connection level
   (`ECONNRESET`) — College Board blocks non-browser clients.
3. Second run: even robots.txt was unreachable; the robots gate closed the
   host (`blocked_robots`) — the fail-safe working as designed.

**Resolution:** the `--intake` path. A human downloads the PDFs in a normal
browser (consistent with College Board's personal-educational-use terms),
drops them into `data/raw/_inbox/collegeboard-paper-practice-tests/`, and
runs `python src/qbank/downloader.py --intake`. Files are then validated,
hashed, and ledgered with status `manual_intake`. Instructions:
[`data/raw/_inbox/collegeboard-paper-practice-tests/HOW_TO_DOWNLOAD.txt`](../data/raw/_inbox/collegeboard-paper-practice-tests/HOW_TO_DOWNLOAD.txt).
These files carry usage tag `RESTRICTED_INTERNAL_USE_ONLY_DO_NOT_REDISTRIBUTE`
and a `RESTRICTED_README.txt` marker is written next to them.

## Reproducing

```
python src/qbank/downloader.py            # idempotent; safe to re-run
python src/qbank/downloader.py --intake   # after manually downloading CB PDFs
```

Outputs: `data/raw/<source_id>/*.pdf`, ledger table `collection_ledger` in
`data/registry/sources.db`, CSV export `data/registry/collection_ledger.csv`.

## Design decisions worth noting

- **Fail-safe robots handling.** Most crawlers treat an unreachable
  robots.txt as "allowed". This pipeline treats it as "closed": if a host
  won't even serve its robots policy to us, we don't fetch content from it
  automatically.
- **Checksum-verified idempotency.** Re-runs don't just check file existence;
  they re-hash every file and compare against the ledger, so silent
  corruption or manual tampering triggers a clean re-download.
- **A ledger row for every decision**, not just successes — skips, robots
  blocks, and failures are all recorded with reasons, so the collection run
  is fully auditable.
