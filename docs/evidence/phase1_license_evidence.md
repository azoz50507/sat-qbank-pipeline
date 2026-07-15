# Phase 1 — Licensing Evidence Log

All evidence gathered 2026-07-15. Each entry: what was checked, where, and
what was found. Findings are paraphrased; consult the linked pages for exact
wording.

---

## Approved sources

### sat-1926-original — Scholastic Aptitude Test (1926)
- **Checked:** Wikimedia Commons file page
  <https://commons.wikimedia.org/wiki/File:Scholastic_Aptitude_Test_(SAT)_from_1926.pdf>
- **Found:** File carries a US public-domain tag: published (or registered
  with the US Copyright Office) before January 1, 1931. Original publication
  1926 by the College Entrance Examination Board.
- **Direct file:** `https://upload.wikimedia.org/wikipedia/commons/a/a5/Scholastic_Aptitude_Test_%28SAT%29_from_1926.pdf`
- **Also on:** Wikisource (proofread transcription pages exist).

### ceeb-math-1911-1915 / ceeb-math-1916-1920 — CEEB Examination Questions in Mathematics
- **Checked:** Internet Archive item pages
  <https://archive.org/details/questmathematics00collrich> (3rd series, 1911–1915),
  <https://archive.org/details/mathematicsquest00collrich> (4th series, 1916–1920)
- **Found:** Published by Ginn and Company for the College Entrance
  Examination Board; both volumes predate 1931 → US public domain. Free
  unrestricted downloads offered (not controlled lending).
- **Note:** Explicit rights metadata field to be re-confirmed via
  `https://archive.org/metadata/<id>` during Phase 2 collection.

### ceeb-history-c1915 — CEEB Examination Questions in History
- **Checked:** <https://archive.org/details/questexamination00collrich>
- **Found:** Rights status **NOT_IN_COPYRIGHT** in item metadata. Free
  download in multiple formats (B/W PDF 1.5 MB, standard PDF 2.0 MB, full
  text, EPUB). 47 pages, scanned from University of California Libraries.
  Publication c. 1915.

### ceeb-history-1901-1905 — CEEB Examination Questions in History, 1901–1905
- **Checked:** <https://archive.org/details/examinationques01boargoog>
- **Found:** Google Books scan of a 1905-era CEEB publication → US public
  domain by publication date.

### wikibooks-sat-study-guide — Wikibooks SAT Study Guide
- **Checked:** <https://en.wikibooks.org/wiki/SAT_Study_Guide>
- **Found:** Footer states text is available under the Creative Commons
  Attribution-ShareAlike license. However the book is ~0% developed — the
  practice-test section is an empty stub. Approved on license, deprioritized
  on content value.

---

## Conditional source

### collegeboard-paper-practice-tests — Official SAT Paper Practice Tests
- **Checked:**
  - <https://satsuite.collegeboard.org/sat/practice-preparation/practice-tests>
    — confirms free full-length paper (nonadaptive) practice-test PDFs.
  - <https://satsuite.collegeboard.org/k12-educators/educator-experience/student-data-privacy-agreement>
    — SAT Suite Program Agreement: College Board is exclusive owner of all
    rights in the SAT and all individual test items; reproducing/posting
    questions without express written permission is prohibited; official
    practice tests may be used by students in noncommercial educational
    settings.
  - <https://privacy.collegeboard.org/copyright-trademark/request-instructions>
    — formal permission-request process exists, confirming no open license.
- **Found:** Free ≠ open. Download for personal educational use is consistent
  with the terms; redistribution of PDFs or extracted questions is not.
- **Caveat:** Direct automated fetches of `collegeboard.org` terms pages were
  blocked (ECONNRESET / 60 s timeout on three attempts — bot protection).
  License position established from the College Board pages above reached via
  search engine. **Re-verify manually in a browser before collection.**

---

## Rejected sources

### collegeboard-educator-question-bank
- **Checked:** SAT Suite Program Agreement (link above).
- **Found:** Uploading, posting, caching, reproducing, or modifying any
  portion of the SAT Suite Question Bank without express written permission
  is prohibited — which is precisely what pipeline collection would do.

### khan-academy-sat-practice
- **Checked:**
  <https://support.khanacademy.org/hc/en-us/articles/42929097425037>,
  <https://www.khanacademy.org/about/tos>
- **Found:** ToS prohibits scraping tools/bots to copy or extract data and
  prohibits using content to train/test/develop AI or ML tools; service is
  personal non-commercial use only. SAT items remain College Board copyright.

### cracksat-net
- **Checked:** <https://www.cracksat.net/about/copyright.html>
- **Found:** Site claims its own copyright over hosted content with no
  evidence of College Board authorization; hosts College Board practice
  tests. Treated as unauthorized redistribution.

### opensat-github
- **Checked:** <https://github.com/Anas099X/OpenSAT>
- **Found:** Open-source repo + free JSON API of SAT questions, community and
  AI generated. No content license distinct from the code license; no
  provenance audit. Risk of derivation from copyrighted College Board items.

### archive-10-sats-1983 / archive-real-sat-subject-tests
- **Checked:** <https://archive.org/details/10satsactualcomp00coll>,
  <https://archive.org/details/realsatsubjectte00coll>
- **Found:** 1983 and 2006 College Board publications; post-1930, in
  copyright; Internet Archive offers controlled lending only, which grants no
  reproduction or collection rights.
