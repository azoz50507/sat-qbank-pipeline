"""Unit tests for the release validation gate (qbank.package)."""

from qbank.package import partition_for, validate_item


def make_record(**overrides) -> dict:
    record = {
        "item_id": "src:doc:p0010:1", "source_id": "src", "doc": "doc",
        "page_num": 10, "item_seq": 1, "number_label": "13",
        "kind": "multiple_choice",
        "stem": "Which value of x satisfies the equation shown?",
        "choices": ["A) 2", "B) 4", "C) 8", "D) 16"],
        "flags": [], "status": "ok", "extraction_source": "text_layer",
        "ocr_mean_conf": None, "usage_tag": "PUBLIC_DOMAIN",
        "page_image": "data/pages/src/doc/page_0010.png", "answer": None,
    }
    record.update(overrides)
    return record


def test_clean_record_passes():
    errors, warnings = validate_item(make_record())
    assert errors == [] and warnings == []

def test_missing_stem_is_a_warning_not_an_error():
    errors, warnings = validate_item(make_record(stem="  "))
    assert errors == [] and "empty stem" in warnings

def test_missing_required_field_fails():
    errors, _ = validate_item(make_record(item_id=""))
    assert any("item_id" in e for e in errors)

def test_bad_page_number_fails():
    errors, _ = validate_item(make_record(page_num=0))
    assert any("page_num" in e for e in errors)

def test_unknown_kind_fails():
    errors, _ = validate_item(make_record(kind="essay"))
    assert any("unknown kind" in e for e in errors)

def test_multiple_choice_needs_two_choices():
    errors, _ = validate_item(make_record(choices=["A) only one"]))
    assert any("choice(s)" in e for e in errors)

def test_duplicate_choice_letters_fail():
    errors, _ = validate_item(make_record(choices=["A) x", "A) y"]))
    assert any("duplicate" in e for e in errors)

def test_answer_letter_must_exist_among_choices():
    record = make_record(answer={"correct_choice": "E", "consistent": True})
    errors, _ = validate_item(record)
    assert any("answer letter E" in e for e in errors)

def test_consistent_answer_passes():
    record = make_record(answer={"correct_choice": "C", "consistent": True})
    errors, _ = validate_item(record)
    assert errors == []

def test_unknown_usage_tag_fails():
    errors, _ = validate_item(make_record(usage_tag="MYSTERY"))
    assert any("usage tag" in e for e in errors)

def test_needs_review_is_a_warning():
    _, warnings = validate_item(make_record(status="needs_review"))
    assert "needs_review" in warnings

def test_partitioning_by_usage_tag():
    assert partition_for(make_record()) == "public"
    assert partition_for(make_record(
        usage_tag="RESTRICTED_INTERNAL_USE_ONLY_DO_NOT_REDISTRIBUTE")) == "restricted"


def test_choice_shape_defects_are_quarantinable():
    from qbank.package import is_quarantinable
    assert is_quarantinable(["multiple_choice with 1 choice(s)"])
    assert is_quarantinable(["duplicate choice letters",
                             "answer letter E not among choices"])

def test_integrity_errors_are_not_quarantinable():
    from qbank.package import is_quarantinable
    assert not is_quarantinable(["missing required field: item_id"])
    assert not is_quarantinable(["duplicate choice letters",
                                 "unknown kind: 'essay'"])
    assert not is_quarantinable([])
