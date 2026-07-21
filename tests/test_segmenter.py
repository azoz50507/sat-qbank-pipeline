"""Unit tests for question segmentation (qbank.segmenter)."""

from qbank.segmenter import QuestionItem, item_status, segment_page


# --- question starts ---------------------------------------------------------

def test_numbered_items_split_in_order():
    items = segment_page(
        "1. If x + 2 = 7, what is the value of x for this problem?\n"
        "Some continuation line.\n"
        "2. A train travels sixty miles in ninety minutes on average.\n"
    )
    assert [i.number_label for i in items] == ["1", "2"]
    assert "continuation" in items[0].stem

def test_years_never_open_an_item():
    items = segment_page("1926. was the first administration of the test.\n")
    assert items == []

def test_number_alone_with_nothing_after_is_not_a_start():
    assert segment_page("14\n") == []

def test_standalone_number_layout_opens_item_before_real_text():
    items = segment_page(
        "13\n"
        "Organic farming is a method of growing food that tries to help.\n"
        "Which choice most effectively uses data from the graph?\n"
        "A) Washington had between 600 and 800 organic\n"
        "farms.\n"
        "B) New York had fewer than 800 organic farms.\n"
    )
    assert len(items) == 1
    assert items[0].number_label == "13"
    assert items[0].kind == "multiple_choice"
    assert items[0].choices[0].endswith("organic farms.")

def test_module_labels_and_separators_do_not_open_items():
    items = segment_page(
        "Module\n"
        "1\n"
        "---------~\n"
        "13\n"
        "A question stem long enough to be treated as a real question here.\n"
    )
    assert [i.number_label for i in items] == ["13"]

def test_dotted_separator_lines_are_not_glued_to_choices():
    items = segment_page(
        "9. Which of the following is a correct statement about x?\n"
        "A) It is even.\n"
        "B) It is odd.\n"
        "..................................................\n"
    )
    assert items[0].choices[-1] == "B) It is odd."

def test_ocr_comma_after_number_still_opens_item():
    items = segment_page(
        "18, A man spent one-eighth of his spare change for a package.\n"
    )
    assert items[0].number_label == "18"

def test_roman_numeral_with_substantial_stem():
    items = segment_page(
        "IV. Compare the administrations of Alexander and of Rome in detail.\n"
    )
    assert len(items) == 1
    assert "roman_numbered" in items[0].flags

def test_roman_numeral_with_short_text_is_rejected():
    assert segment_page("I. am short\n") == []


# --- choices & kinds ---------------------------------------------------------

def test_choice_lines_make_multiple_choice():
    items = segment_page(
        "3. Which value of x satisfies the equation shown above today?\n"
        "A) 2\n"
        "B) 4\n"
        "C) 8\n"
        "D) 16\n"
    )
    assert items[0].kind == "multiple_choice"
    assert len(items[0].choices) == 4
    assert items[0].choices[0] == "A) 2"

def test_wrapped_choice_text_joins_previous_choice():
    items = segment_page(
        "5. Which statement best describes the author's central claim below?\n"
        "A) The migration was driven primarily by economic\n"
        "necessity rather than choice.\n"
        "B) The author disagrees with earlier historians completely.\n"
    )
    assert "necessity rather than choice" in items[0].choices[0]

def test_ans_blank_makes_free_response():
    items = segment_page(
        "7. If two pencils cost five cents, how many for fifty cents?\n"
        "Ans.________pencils\n"
    )
    assert items[0].kind == "free_response"
    assert "Ans" not in items[0].stem

def test_lowercase_subparts_stay_in_stem():
    items = segment_page(
        "2. Answer both parts of the following algebra question fully.\n"
        "(a) Simplify the first expression completely.\n"
        "(b) Solve the second equation for x.\n"
    )
    assert len(items) == 1
    assert items[0].kind == "unknown"
    assert "has_subparts" in items[0].flags


# --- flags & status ----------------------------------------------------------

def test_truncation_flag_at_page_end():
    items = segment_page(
        "9. A regiment marched one hundred miles in four days and then\n"
    )
    assert "truncated_at_page_end" in items[0].flags

def test_short_stem_is_flagged():
    items = segment_page("4. Define war.\nAns.____\n")
    assert "short_stem" in items[0].flags

def test_status_review_for_flagged_items():
    item = QuestionItem(number_label="1", stem="x", flags=["short_stem"])
    assert item_status(item, "text_layer", None) == "needs_review"

def test_status_review_for_low_confidence_ocr():
    item = QuestionItem(number_label="1", stem="a perfectly fine stem here")
    assert item_status(item, "ocr", 55.0) == "needs_review"

def test_status_ok_for_clean_text_layer_item():
    item = QuestionItem(number_label="1", stem="a perfectly fine stem here")
    assert item_status(item, "text_layer", None) == "ok"
