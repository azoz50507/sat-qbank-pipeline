"""Unit tests for answer parsing and Q/A alignment (qbank.answers)."""

from qbank.answers import (AnswerEntry, align_pair, assign_blocks,
                           page_block_label, parse_answer_page)


# --- page headers ------------------------------------------------------------

def test_reading_writing_header():
    assert page_block_label("SAT ANSWER EXPLANATIONS n READING AND WRITING: MODULE 1") == "RW1"

def test_math_header():
    assert page_block_label("SAT ANSWER EXPLANATIONS n MATH: MODULE 2") == "M2"

def test_header_must_be_near_top():
    assert page_block_label("x" * 300 + "MATH: MODULE 1") is None


# --- entry parsing -----------------------------------------------------------

PAGE = """SAT ANSWER EXPLANATIONS n READING AND WRITING: MODULE 1
QUESTION 2
Choice A is the best answer because it most logically completes the text.
Choice B is incorrect because it would not make sense.
QUESTION 3
The correct answer is C. It follows from the passage directly.
"""

def test_question_heads_split_entries():
    block, entries = parse_answer_page(PAGE)
    assert block == "RW1"
    assert [e.number_label for e in entries] == ["2", "3"]

def test_best_answer_choice_extracted():
    _, entries = parse_answer_page(PAGE)
    assert entries[0].correct_choice == "A"

def test_correct_answer_is_letter_extracted():
    _, entries = parse_answer_page(PAGE)
    assert entries[1].correct_choice == "C"

def test_spr_numeric_answer_with_math_typography_flag():
    _, entries = parse_answer_page(
        "SAT ANSWER EXPLANATIONS n MATH: MODULE 1\n"
        "QUESTION 21\n"
        "The correct answer is 361\n"
        "8 . The rational exponent property applies here.\n"
    )
    entry = entries[0]
    assert entry.answer_text == "361"
    assert "spr_text_answer" in entry.flags
    assert "verify_math_typography" in entry.flags

def test_entry_without_answer_is_flagged():
    _, entries = parse_answer_page(
        "QUESTION 9\nThis explanation never states the answer explicitly.\n"
    )
    assert "no_answer_found" in entries[0].flags


# --- block detection ---------------------------------------------------------

def test_blocks_reset_on_drop_to_small_number():
    numbers = [1, 2, 27, 1, 5, 27, 1, 22, 1, 22]
    assert assign_blocks(numbers) == [0, 0, 0, 1, 1, 1, 2, 2, 3, 3]

def test_junk_decrease_does_not_open_block():
    # a stray '45' then back to 26: same block (26 > reset max)
    assert assign_blocks([24, 45, 26, 27]) == [0, 0, 0, 0]

def test_missing_first_question_still_resets():
    assert assign_blocks([26, 27, 2, 3]) == [0, 0, 1, 1]


# --- alignment ---------------------------------------------------------------

def test_module_duplicate_numbers_align_by_block_position():
    items = [("t:p1:1", "1"), ("t:p2:1", "2"), ("t:p3:1", "1"), ("t:p4:1", "2")]
    answer_blocks = [
        ("RW1", {"1": AnswerEntry("1", correct_choice="A"),
                 "2": AnswerEntry("2", correct_choice="B")}),
        ("RW2", {"1": AnswerEntry("1", correct_choice="C"),
                 "2": AnswerEntry("2", correct_choice="D")}),
    ]
    matched, unmatched, orphans = align_pair(items, answer_blocks)
    assert [m.correct_choice for m in matched] == ["A", "B", "C", "D"]
    assert matched[2].answer_block == "RW2"
    assert unmatched == [] and orphans == 0

def test_unmatched_question_and_orphan_answer_are_counted():
    items = [("t:p1:1", "1"), ("t:p1:2", "3")]
    answer_blocks = [("RW1", {"1": AnswerEntry("1", correct_choice="A"),
                              "2": AnswerEntry("2", correct_choice="B")})]
    matched, unmatched, orphans = align_pair(items, answer_blocks)
    assert len(matched) == 1
    assert unmatched == [("t:p1:2", "3")]
    assert orphans == 1

def test_non_numeric_labels_are_ignored():
    matched, unmatched, orphans = align_pair(
        [("t:p1:1", "IV")], [("RW1", {"4": AnswerEntry("4")})])
    assert matched == [] and unmatched == [] and orphans == 1

def test_junk_number_does_not_derail_the_cursor():
    # a stray '2' mid-module: no '2' within the window ahead -> unmatched,
    # and the following real questions still align
    items = [("a", "20"), ("junk", "2"), ("b", "21"), ("c", "22")]
    table = {str(n): AnswerEntry(str(n), correct_choice="A") for n in range(1, 24)}
    matched, unmatched, _ = align_pair(items, [("RW1", table)])
    assert [m.number_label for m in matched] == ["20", "21", "22"]
    assert unmatched == [("junk", "2")]

def test_cursor_survives_a_run_of_missed_questions():
    # questions 2-6 missing from segmentation; 7 is within the window
    items = [("a", "1"), ("b", "7"), ("c", "8")]
    table = {str(n): AnswerEntry(str(n)) for n in range(1, 9)}
    matched, unmatched, orphans = align_pair(items, [("M1", table)])
    assert [m.number_label for m in matched] == ["1", "7", "8"]
    assert orphans == 5
