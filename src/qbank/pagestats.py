"""Per-page quality statistics and routing decisions (Phase 3).

Pure logic, no I/O: the renderer computes raw measurements per page and
hands them to :func:`classify_page`, which returns a classification, an
extraction route, and a human-readable reason. Keeping this module free of
side effects makes every threshold and rule directly unit-testable.

Classifications:
    content     - a page carrying question/answer material worth extracting
    answer_key  - answer key / answer explanations / scoring material
    cover       - title or cover page at the start of a document
    index       - table of contents or index page
    blank       - empty or near-empty page (incl. "no test material" dividers)

Routes:
    text   - embedded text layer is usable: text-based extraction path
    image  - text layer missing or garbled: image/OCR extraction path
    skip   - page carries nothing extractable (blank/cover/index)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- Thresholds (tuned on the Phase 2 corpus; see docs/phase3_README.md) ---

BLANK_MAX_CHARS = 20      # a truly blank page has at most stray OCR noise
BLANK_MAX_INK = 0.004     # <0.4% dark pixels in the central region
SPARSE_MAX_CHARS = 150    # below this a page has no extractable substance
SPARSE_MAX_INK = 0.010    # ...unless there is ink suggesting graphics/scan
COVER_MAX_PAGE = 2        # covers live in the first two pages
COVER_MAX_CHARS = 350     # covers are text-sparse (title, logo, notice)
INDEX_MAX_WORDS = 450     # TOC pages are word-limited lists
TEXT_ROUTE_MIN_CHARS = 200   # need enough text for the text-based path
TEXT_ROUTE_MIN_ALNUM = 0.55  # below this the layer is likely OCR garbage

HEAD_WINDOW = 600         # chars from the top of the page used for patterns

# NOTE: Phase 6 QA removed two loose patterns that misclassified exam pages
# whose *instructions* mention answers ("Correct answers to eight questions
# constitute a full paper", CEEB volumes). What remains are strong
# answer-section markers plus a standalone ANSWERS heading.
ANSWER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"answer\s+key",
        r"answer\s+explanations?",
        r"scoring\s+your",
    )
]

# A bare "ANSWERS" heading only counts near the very top of the page:
# in old scans, line-wrapped prose puts the word alone on a line mid-page.
STANDALONE_ANSWERS = re.compile(r"(?mi)^\s*answers\s*$")
STANDALONE_ANSWERS_WINDOW = 120

INDEX_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.MULTILINE)
    for p in (
        r"table\s+of\s+contents",
        r"^\s*contents\s*$",
        r"^\s*index\s*$",
    )
]


@dataclass(frozen=True)
class PageStats:
    """Raw measurements for one rendered page."""

    page_num: int          # 1-based position in the document
    doc_page_count: int
    width_pt: float
    height_pt: float
    text_chars: int        # length of the stripped embedded text layer
    word_count: int
    alnum_ratio: float     # alphanumeric chars / non-space chars (0 if no text)
    ink_ratio: float       # dark-pixel fraction of the central 90% region
    head_text: str = ""    # first HEAD_WINDOW chars of the text layer


@dataclass(frozen=True)
class Decision:
    classification: str
    route: str
    reason: str


def orientation(stats: PageStats) -> str:
    return "landscape" if stats.width_pt > stats.height_pt else "portrait"


def _matches_any(patterns: list[re.Pattern], text: str) -> re.Pattern | None:
    for pattern in patterns:
        if pattern.search(text):
            return pattern
    return None


def _route_for_content(stats: PageStats, classification: str, why: str) -> Decision:
    """Content-bearing pages go to the text path only if the layer is usable."""
    if stats.text_chars >= TEXT_ROUTE_MIN_CHARS and stats.alnum_ratio >= TEXT_ROUTE_MIN_ALNUM:
        return Decision(
            classification, "text",
            f"{why}; text layer usable ({stats.text_chars} chars, "
            f"alnum {stats.alnum_ratio:.2f})",
        )
    if stats.text_chars < TEXT_ROUTE_MIN_CHARS:
        detail = f"text layer too thin ({stats.text_chars} chars < {TEXT_ROUTE_MIN_CHARS})"
    else:
        detail = f"text layer looks garbled (alnum {stats.alnum_ratio:.2f} < {TEXT_ROUTE_MIN_ALNUM})"
    return Decision(classification, "image", f"{why}; {detail} -> image/OCR path")


def classify_page(stats: PageStats) -> Decision:
    """Map one page's measurements to (classification, route, reason)."""
    head = stats.head_text[:HEAD_WINDOW]

    # 1. Blank: nothing on the page at all.
    if stats.text_chars <= BLANK_MAX_CHARS and stats.ink_ratio <= BLANK_MAX_INK:
        return Decision(
            "blank", "skip",
            f"no text ({stats.text_chars} chars) and no ink "
            f"({stats.ink_ratio:.4f} <= {BLANK_MAX_INK})",
        )

    # 2. Answer material announces itself in the page header.
    if (pattern := _matches_any(ANSWER_PATTERNS, head)) is not None:
        return _route_for_content(
            stats, "answer_key", f"header matches answer pattern /{pattern.pattern}/"
        )
    if STANDALONE_ANSWERS.search(head[:STANDALONE_ANSWERS_WINDOW]):
        return _route_for_content(
            stats, "answer_key", "standalone ANSWERS heading at page top"
        )

    # 3. Table of contents / index pages.
    if (pattern := _matches_any(INDEX_PATTERNS, head)) is not None and stats.word_count <= INDEX_MAX_WORDS:
        return Decision(
            "index", "skip",
            f"header matches index pattern /{pattern.pattern}/ "
            f"with {stats.word_count} words",
        )

    # 4. Covers: early, text-sparse pages.
    if stats.page_num <= COVER_MAX_PAGE and stats.text_chars < COVER_MAX_CHARS:
        return Decision(
            "cover", "skip",
            f"page {stats.page_num} of {stats.doc_page_count} with sparse text "
            f"({stats.text_chars} chars < {COVER_MAX_CHARS})",
        )

    # 5. Substantial text, or real ink (scanned content without a text layer).
    if stats.text_chars >= SPARSE_MAX_CHARS:
        return _route_for_content(
            stats, "content", f"substantial text ({stats.text_chars} chars)"
        )
    if stats.ink_ratio >= SPARSE_MAX_INK:
        return _route_for_content(
            stats, "content",
            f"little text ({stats.text_chars} chars) but real ink "
            f"({stats.ink_ratio:.3f}) suggests scanned/graphic content",
        )

    # 6. Fallback: sparse dividers ("no test material on this page").
    return Decision(
        "blank", "skip",
        f"near-blank divider: {stats.text_chars} chars, ink {stats.ink_ratio:.4f}",
    )
