"""Unit tests for page classification and routing (qbank.pagestats)."""

from qbank.pagestats import PageStats, classify_page, orientation


def make_stats(**overrides) -> PageStats:
    """A plain content-ish page; tests override what they probe."""
    defaults = dict(
        page_num=10, doc_page_count=60, width_pt=612.0, height_pt=792.0,
        text_chars=1200, word_count=220, alnum_ratio=0.80, ink_ratio=0.05,
        head_text="If x + 2 = 7, what is the value of x?",
    )
    defaults.update(overrides)
    return PageStats(**defaults)


# --- classification ---------------------------------------------------------

def test_truly_blank_page():
    decision = classify_page(make_stats(text_chars=0, word_count=0,
                                        alnum_ratio=0.0, ink_ratio=0.001, head_text=""))
    assert decision.classification == "blank"
    assert decision.route == "skip"


def test_sparse_divider_counts_as_blank():
    decision = classify_page(make_stats(
        text_chars=40, word_count=8, ink_ratio=0.005,
        head_text="NO TEST MATERIAL ON THIS PAGE",
    ))
    assert decision.classification == "blank"
    assert decision.route == "skip"


def test_cover_is_early_and_text_sparse():
    decision = classify_page(make_stats(page_num=1, text_chars=120, word_count=18,
                                        ink_ratio=0.03, head_text="The SAT"))
    assert decision.classification == "cover"
    assert decision.route == "skip"


def test_text_heavy_first_page_is_content_not_cover():
    decision = classify_page(make_stats(page_num=1, text_chars=2000))
    assert decision.classification == "content"


def test_answer_explanations_header_wins():
    decision = classify_page(make_stats(
        head_text="SAT Practice Test #4 Answer Explanations - Reading and Writing"
    ))
    assert decision.classification == "answer_key"
    assert decision.route == "text"


def test_scoring_page_is_answer_material():
    decision = classify_page(make_stats(head_text="Scoring Your Paper SAT Practice Test"))
    assert decision.classification == "answer_key"


def test_table_of_contents_is_index():
    decision = classify_page(make_stats(
        page_num=3, text_chars=500, word_count=90,
        head_text="CONTENTS\nIntroduction ......... 3\nMathematics ......... 9",
    ))
    assert decision.classification == "index"
    assert decision.route == "skip"


# --- routing ----------------------------------------------------------------

def test_good_text_layer_routes_to_text():
    decision = classify_page(make_stats(text_chars=900, alnum_ratio=0.75))
    assert (decision.classification, decision.route) == ("content", "text")


def test_garbled_text_layer_routes_to_image():
    decision = classify_page(make_stats(text_chars=800, alnum_ratio=0.30))
    assert (decision.classification, decision.route) == ("content", "image")
    assert "garbled" in decision.reason


def test_scanned_page_without_text_layer_routes_to_image():
    decision = classify_page(make_stats(text_chars=50, word_count=9,
                                        alnum_ratio=0.9, ink_ratio=0.08))
    assert (decision.classification, decision.route) == ("content", "image")


def test_route_thresholds_are_inclusive():
    decision = classify_page(make_stats(text_chars=200, alnum_ratio=0.55))
    assert decision.route == "text"


# --- geometry ---------------------------------------------------------------

def test_orientation_portrait_and_landscape():
    assert orientation(make_stats()) == "portrait"
    assert orientation(make_stats(width_pt=792.0, height_pt=612.0)) == "landscape"
