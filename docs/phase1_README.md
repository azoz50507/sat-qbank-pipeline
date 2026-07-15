# Phase 1 — Source Discovery & Licensing Vetting

**Status: complete** · Vetting date: 2026-07-15

## Goal

Identify candidate sources of SAT / SAT-style practice material, verify the
license or terms of use for each one against primary evidence, and record an
auditable approve / reject decision in a source registry before a single byte
is collected.

## Method

1. **Discovery.** Searched for four families of material: official College
   Board releases, open educational repositories (Wikimedia projects),
   archived historical materials (Internet Archive), and community projects
   (GitHub).
2. **Verification.** For each candidate, fetched the license statement, terms
   of service, or rights metadata from the publisher itself (or from the
   hosting archive's rights statement) and recorded the URL, a summary of the
   finding, and the retrieval date.
3. **Decision.** Assigned one of three statuses:

   | Status | Meaning |
   |--------|---------|
   | `approved` | Public domain or open license (CC BY-SA). Collectible without restriction (attribution where required). |
   | `conditional` | Officially free to download but **not** openly licensed (all rights reserved). Personal, non-commercial educational use only; no redistribution. Collection requires explicit project-owner sign-off. |
   | `rejected` | Terms prohibit collection, content is under copyright without permission, or provenance is unverifiable. |

4. **Recording.** All decisions live in `data/registry/seed_sources.json`
   (human-curated source of truth), loaded into SQLite
   (`data/registry/sources.db`) and exported to CSV
   (`data/registry/source_registry.csv`) by `src/qbank/registry.py`.

## Results

13 candidate sources vetted: **6 approved · 1 conditional · 6 rejected.**

### Approved (public domain / open license)

| Source | Year | License basis |
|--------|------|---------------|
| Scholastic Aptitude Test (1926) — the original first SAT | 1926 | US public domain (published before 1931), verified on Wikimedia Commons |
| CEEB Examination Questions in Mathematics, 3rd series | 1911–1915 | US public domain, Internet Archive free download |
| CEEB Examination Questions in Mathematics, 4th series | 1916–1920 | US public domain, Internet Archive free download |
| CEEB Examination Questions in History | c. 1915 | Explicit `NOT_IN_COPYRIGHT` rights statement on Internet Archive |
| CEEB Examination Questions in History, 1901–1905 | 1905 | US public domain (Google Books scan) |
| Wikibooks: SAT Study Guide | ongoing | CC BY-SA — approved but deprioritized (content nearly empty) |

### Conditional

| Source | Why conditional |
|--------|-----------------|
| College Board Official SAT Paper Practice Tests (PDF) | Free official downloads, but copyright College Board: personal non-commercial educational use only, redistribution prohibited. Collectible only with project-owner sign-off and private outputs. |

### Rejected

| Source | Reason |
|--------|--------|
| College Board SAT Suite Educator Question Bank | Terms explicitly prohibit caching/reproducing question bank items |
| Khan Academy Official SAT Practice | ToS prohibits scraping; content is College Board copyright |
| CrackSAT.net | Unauthorized redistribution of copyrighted College Board tests |
| OpenSAT (GitHub) | Code license ≠ content license; question provenance unverifiable |
| Archive.org "10 SATs" (1983) | In copyright; lending access grants no collection rights |
| Archive.org "Real SAT Subject Tests" (2006) | In copyright; lending access grants no collection rights |

Full per-source evidence (URLs, findings, retrieval dates) is in
[`docs/evidence/phase1_license_evidence.md`](evidence/phase1_license_evidence.md)
and embedded in the registry itself.

## Key insight

Virtually all *modern* SAT material is copyrighted regardless of how freely it
is distributed. The unrestricted backbone of this pipeline is therefore
**historical**: the original 1926 SAT and four CEEB examination-question
volumes (1901–1920), all in the US public domain (pre-1931 publication).
These provide genuine standardized-test PDFs — including math question sets —
that can be collected, processed, and redistributed without restriction.

## Reproducing

```
python src/qbank/registry.py
```

Idempotent: rebuilds the SQLite registry and CSV export from the seed file
and prints the vetting summary.

## Known limitations

- College Board's own terms pages block automated fetching (connection
  resets/timeouts). The `conditional` entry's license position was verified
  through College Board's program-agreement and copyright-permission pages;
  it should be re-verified manually in a browser before any collection.
- Rights statements for two Internet Archive items are inferred from
  pre-1931 publication dates plus unrestricted download availability; the
  explicit metadata rights field is re-checked during Phase 2 collection.
