"""Question segmentation logic (Phase 5).

Pure functions that split one page of exam text into structured question
items. No I/O - the extraction driver (``extract.py``) feeds it text and
persists the results - so every heuristic is directly unit-testable.

Item anatomy detected:

- **Question starts**: arabic-numbered lines (``7.`` / ``7)``, 1-3 digits,
  so years like ``1926.`` never match) and conservatively-guarded roman
  numerals (``IV.`` with a substantial stem) used by the oldest CEEB
  volumes.
- **Choices**: uppercase ``A)`` .. ``E)`` lines (also ``(A)`` / ``A.``)
  make an item ``multiple_choice``. Lowercase ``(a)`` sub-parts stay inside
  the stem and set a ``has_subparts`` flag.
- **Answer blanks**: ``Ans.____`` lines (the 1926 SAT style) make an item
  ``free_response`` and are stripped from the stem.

Every suspicious structure gets a flag rather than a silent guess; flags
drive the ok / needs_review status assigned by the driver.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ARABIC_START = re.compile(r"^\s{0,8}(\d{1,3})[.),]\s+(\S.*)$")
ROMAN_START = re.compile(r"^\s{0,8}([IVX]{1,5})[.)]\s+(\S.*)$")
CHOICE_LINE = re.compile(r"^\s*\(?([A-E])[.)\]]\s+(\S.*)$")
ANS_BLANK = re.compile(r"^\s*Ans\b[.,:]?[\s_\-]*", re.IGNORECASE)
SUBPART = re.compile(r"^\s*\(([a-e])\)\s+")
INLINE_CHOICES = re.compile(r"\bA[.)]\s+\S.*\bB[.)]\s+\S", re.DOTALL)
STANDALONE_NUM = re.compile(r"^\s{0,8}(\d{1,3})\s*[.)]?\s*$")
NOISE_LINE = re.compile(r"^\s*[.\-_~=·]{4,}\s*$")

MIN_STEM_CHARS = 15          # anything shorter is probably a misfire
ROMAN_MIN_STEM = 20          # roman numerals need a beefier guard ("I." etc.)
STANDALONE_MIN_NEXT = 15     # a lone number opens an item only before real text
STANDALONE_MAX_NUM = 60      # figure/axis labels (100, 110) are not questions
MODULE_LABEL = re.compile(r"^\s*module\s*$", re.IGNORECASE)
TERMINAL_PUNCT = ".?!):;\"'"


@dataclass
class QuestionItem:
    number_label: str
    stem: str
    choices: list[str] = field(default_factory=list)
    kind: str = "unknown"          # multiple_choice | free_response | unknown
    start_line: int = 0            # 0-based line index on the page
    flags: list[str] = field(default_factory=list)


def _is_question_start(line: str) -> tuple[str, str] | None:
    """Return (number_label, first_stem_text) if the line opens an item."""
    match = ARABIC_START.match(line)
    if match:
        return match.group(1), match.group(2)
    match = ROMAN_START.match(line)
    if match and len(match.group(2).strip()) >= ROMAN_MIN_STEM:
        return match.group(1), match.group(2)
    return None


def _finalize(item: QuestionItem, body: list[str]) -> QuestionItem:
    """Split an item's raw body lines into stem / choices / answer format."""
    stem_lines: list[str] = []
    choices: list[str] = []
    free_response = False

    for line in body:
        if ANS_BLANK.match(line):
            free_response = True
            continue
        choice = CHOICE_LINE.match(line)
        if choice:
            choices.append(f"{choice.group(1)}) {choice.group(2).strip()}")
            continue
        if choices:
            # continuation of the previous choice's wrapped text
            choices[-1] = f"{choices[-1]} {line.strip()}".strip()
        else:
            stem_lines.append(line.strip())

    item.stem = " ".join(part for part in stem_lines if part).strip()
    item.choices = choices

    if choices:
        item.kind = "multiple_choice"
        if len(choices) < 2:
            item.flags.append("lonely_choice")
    elif free_response:
        item.kind = "free_response"
    else:
        item.kind = "unknown"

    if len(item.stem) < MIN_STEM_CHARS:
        item.flags.append("short_stem")
    if item.number_label.isalpha():
        item.flags.append("roman_numbered")
    if any(SUBPART.match(part) for part in stem_lines):
        item.flags.append("has_subparts")
    if not choices and INLINE_CHOICES.search(item.stem):
        item.flags.append("inline_choices")
    return item


def segment_page(text: str) -> list[QuestionItem]:
    """Split one page's text into question items, in reading order."""
    lines = text.splitlines()
    items: list[QuestionItem] = []
    current: QuestionItem | None = None
    body: list[str] = []

    def next_meaningful(after: int) -> str | None:
        for j in range(after + 1, len(lines)):
            stripped = lines[j].strip()
            if stripped and not NOISE_LINE.match(lines[j]):
                return stripped
        return None

    def prev_meaningful(before: int) -> str | None:
        for j in range(before - 1, -1, -1):
            stripped = lines[j].strip()
            if stripped and not NOISE_LINE.match(lines[j]):
                return stripped
        return None

    for idx, line in enumerate(lines):
        if NOISE_LINE.match(line):
            continue
        started = _is_question_start(line)
        if started is None:
            # Layout style where the number sits alone on its own line
            # (College Board digital PDFs). Guard: only counts as a start if
            # real text follows - a bare page number at the sheet edge has
            # nothing after it, headers are short, choices belong elsewhere.
            lone = STANDALONE_NUM.match(line)
            if lone and int(lone.group(1)) <= STANDALONE_MAX_NUM:
                previous = prev_meaningful(idx)
                following = next_meaningful(idx)
                if (following and len(following) >= STANDALONE_MIN_NEXT
                        and not CHOICE_LINE.match(following)
                        and not STANDALONE_NUM.match(following)
                        and not (previous and MODULE_LABEL.match(previous))):
                    started = (lone.group(1), "")
        if started:
            if current is not None:
                items.append(_finalize(current, body))
            number, first = started
            current = QuestionItem(number_label=number, stem="", start_line=idx)
            body = [first] if first else []
        elif current is not None and line.strip():
            body.append(line)

    if current is not None:
        item = _finalize(current, body)
        last_text = (item.choices[-1] if item.choices else item.stem).rstrip()
        if item.kind == "unknown" and last_text and last_text[-1] not in TERMINAL_PUNCT:
            item.flags.append("truncated_at_page_end")
        items.append(item)
    return items


def item_status(item: QuestionItem, extraction_source: str,
                ocr_mean_conf: float | None) -> str:
    """ok / needs_review for one item, given how its text was obtained."""
    review_flags = {"short_stem", "truncated_at_page_end", "lonely_choice",
                    "inline_choices"}
    if review_flags & set(item.flags):
        return "needs_review"
    if extraction_source == "ocr" and (ocr_mean_conf or 0) < 70:
        return "needs_review"
    return "ok"
