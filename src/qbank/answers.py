"""Answer-key parsing and question/answer alignment logic (Phase 6).

Pure functions, no I/O (the ``align.py`` driver feeds text in and persists
results), so every rule is unit-testable.

College Board answer-explanation pages carry a section header
("READING AND WRITING: MODULE 1" / "MATH: MODULE 2") that disambiguates
repeating question numbers across modules. Entries start at "QUESTION N"
and state their answer as "Choice C is the best answer ..." or
"The correct answer is 14 ...".

On the question side, numbers restart at each module; blocks are detected
by number resets (a drop back to <= 5), which is robust even when
individual items were missed by segmentation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SECTION_HEADER = re.compile(
    r"(READING\s+AND\s+WRITING|MATH)\s*:\s*MODULE\s*(\d)", re.IGNORECASE)
QUESTION_HEAD = re.compile(r"^\s*QUESTION\s+(\d{1,3})\b", re.IGNORECASE)
BEST_CHOICE = re.compile(
    r"Choice\s+([A-D])\s+is\s+the\s+best\s+answer", re.IGNORECASE)
CORRECT_CHOICE = re.compile(
    r"correct\s+answer\s+is\s+(?:choice\s+)?([A-D])\b", re.IGNORECASE)
CORRECT_TEXT = re.compile(
    r"correct\s+answer\s+is\s+([^\n.]{1,60})", re.IGNORECASE)

HEADER_WINDOW = 200        # section header lives at the top of the page
RATIONALE_MAX = 800
BLOCK_RESET_MAX = 5        # a number this small after a drop starts a block


@dataclass
class AnswerEntry:
    number_label: str
    correct_choice: str | None = None
    answer_text: str | None = None
    rationale: str = ""
    flags: list[str] = field(default_factory=list)


def page_block_label(text: str) -> str | None:
    """Section+module label from a page header, e.g. 'RW1' or 'M2'."""
    match = SECTION_HEADER.search(text[:HEADER_WINDOW])
    if not match:
        return None
    prefix = "RW" if match.group(1).upper().startswith("READING") else "M"
    return f"{prefix}{match.group(2)}"


def _finalize(entry: AnswerEntry, body: list[str], math_block: bool) -> AnswerEntry:
    joined = "\n".join(body)
    choice = BEST_CHOICE.search(joined) or CORRECT_CHOICE.search(joined)
    if choice:
        entry.correct_choice = choice.group(1).upper()
    else:
        text = CORRECT_TEXT.search(joined)
        if text:
            entry.answer_text = text.group(1).strip()
            entry.flags.append("spr_text_answer")
            if math_block:
                # fraction/exponent typesetting splits across lines in the
                # text layer, so the captured value may be incomplete
                entry.flags.append("verify_math_typography")
        else:
            entry.flags.append("no_answer_found")
    entry.rationale = " ".join(joined.split())[:RATIONALE_MAX]
    return entry


def parse_answer_page(text: str) -> tuple[str | None, list[AnswerEntry]]:
    """Parse one answer-explanations page -> (block_label, entries)."""
    block = page_block_label(text)
    math_block = bool(block and block.startswith("M"))
    entries: list[AnswerEntry] = []
    current: AnswerEntry | None = None
    body: list[str] = []

    for line in text.splitlines():
        head = QUESTION_HEAD.match(line)
        if head:
            if current is not None:
                entries.append(_finalize(current, body, math_block))
            current = AnswerEntry(number_label=head.group(1))
            body = []
        elif current is not None and line.strip():
            body.append(line)
    if current is not None:
        entries.append(_finalize(current, body, math_block))
    return block, entries


def assign_blocks(numbers: list[int]) -> list[int]:
    """Block index per position, using number resets.

    A new block starts when the number drops back to <= BLOCK_RESET_MAX.
    Junk decreases (a stray '45' picked up mid-module) do not open blocks,
    and a block whose first question was missed still resets on q2/q3.
    """
    blocks: list[int] = []
    block = 0
    prev: int | None = None
    for num in numbers:
        if prev is not None and num <= prev and num <= BLOCK_RESET_MAX:
            block += 1
        blocks.append(block)
        prev = num
    return blocks


@dataclass(frozen=True)
class Alignment:
    item_id: str
    number_label: str
    block_index: int
    answer_block: str | None
    correct_choice: str | None
    answer_text: str | None
    rationale: str
    answer_flags: tuple[str, ...]


ALIGN_WINDOW = 10    # how far ahead in the canonical sequence a match may sit
                     # (also the confirmation reach for the initial lock-in;
                     # wider "resync" reaches were tried and measurably hurt:
                     # they let stray numbers steal matches from the next
                     # module, cascading misalignment)


def align_pair(
    items: list[tuple[str, str]],
    answer_blocks: list[tuple[str | None, dict[str, AnswerEntry]]],
    window: int = ALIGN_WINDOW,
) -> tuple[list[Alignment], list[tuple[str, str]], int]:
    """Align one test doc's items with its answers doc's entries.

    ``items``: (item_id, number_label) in reading order.
    ``answer_blocks``: ordered (block_label, {number -> AnswerEntry}).

    The answer entries, flattened in document order, form the *canonical*
    question sequence (they are complete and clean). Items are walked in
    reading order with a cursor into that sequence: each item matches the
    nearest unused canonical entry with the same number within ``window``
    positions ahead. This is monotone - it survives missed items (the
    cursor jumps forward), duplicated numbers across modules (the cursor
    has already passed the earlier module), and stray junk numbers (a
    bogus '2' mid-module finds no '2' within the window and is simply
    unmatched, without derailing anything else).
    """
    canonical: list[tuple[int, str | None, str, AnswerEntry]] = []
    for block_idx, (label, table) in enumerate(answer_blocks):
        for num, entry in table.items():
            canonical.append((block_idx, label, num, entry))

    numeric_items = [(iid, num) for iid, num in items if num.isdigit()]
    matched: list[Alignment] = []
    unmatched: list[tuple[str, str]] = []
    used = [False] * len(canonical)
    cursor = 0

    def confirmations(start: int, lookahead: list[tuple[str, str]]) -> int:
        """How many of the next items would fit if we matched at start."""
        pos = start + 1
        confirmed = 0
        for _, next_num in lookahead:
            for j in range(pos, min(pos + window, len(canonical))):
                if not used[j] and canonical[j][2] == next_num:
                    confirmed += 1
                    pos = j + 1
                    break
        return confirmed

    for index, (item_id, num) in enumerate(numeric_items):
        if not matched:
            # Initial lock-in: the whole sequence is searchable, but a
            # candidate position must be CONFIRMED by the following items
            # also fitting - otherwise a stray leading number would drop
            # the cursor deep into the sequence and strand a whole module.
            # Lookahead numbers that exist nowhere in the answers cannot
            # vouch either way, so they do not raise the bar.
            lookahead = numeric_items[index + 1:index + 4]
            confirmable = sum(
                1 for _, nn in lookahead
                if any(not used[j] and canonical[j][2] == nn
                       for j in range(len(canonical)))
            )
            needed = min(2, confirmable)
            hit = None
            for j in range(len(canonical)):
                if not used[j] and canonical[j][2] == num:
                    if confirmations(j, lookahead) >= needed:
                        hit = j
                        break
        else:
            # After lock-in: a strictly bounded forward window.
            limit = min(cursor + window, len(canonical))
            hit = None
            for j in range(cursor, limit):
                if not used[j] and canonical[j][2] == num:
                    hit = j
                    break
        if hit is None:
            unmatched.append((item_id, num))
            continue
        used[hit] = True
        block_idx, label, _, entry = canonical[hit]
        matched.append(Alignment(
            item_id=item_id, number_label=num, block_index=block_idx,
            answer_block=label, correct_choice=entry.correct_choice,
            answer_text=entry.answer_text, rationale=entry.rationale,
            answer_flags=tuple(entry.flags),
        ))
        cursor = hit + 1

    return matched, unmatched, used.count(False)
