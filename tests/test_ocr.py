"""Unit tests for OCR TSV parsing and quality flagging (qbank.ocr)."""

from qbank.ocr import TsvStats, parse_tsv, quality_flag

HEADER = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
          "left\ttop\twidth\theight\tconf\ttext")


def tsv(*rows: str) -> str:
    return "\n".join([HEADER, *rows])


def word(conf: float, text: str = "word", level: int = 5) -> str:
    return f"{level}\t1\t1\t1\t1\t1\t0\t0\t10\t10\t{conf}\t{text}"


# --- parse_tsv ---------------------------------------------------------------

def test_mean_confidence_over_word_rows():
    stats = parse_tsv(tsv(word(90.0), word(70.0)))
    assert stats.word_count == 2
    assert stats.mean_conf == 80.0

def test_container_rows_with_conf_minus_one_are_ignored():
    stats = parse_tsv(tsv(word(-1, level=2), word(88.0)))
    assert stats.word_count == 1
    assert stats.mean_conf == 88.0

def test_whitespace_text_cells_are_noise():
    stats = parse_tsv(tsv(word(95.0, text="   "), word(60.0, text="real")))
    assert stats.word_count == 1
    assert stats.mean_conf == 60.0

def test_empty_page_yields_zero_stats():
    stats = parse_tsv(tsv())
    assert stats == TsvStats(word_count=0, mean_conf=0.0)

def test_malformed_rows_do_not_crash():
    stats = parse_tsv(tsv("garbage line", "1\t2\t3", word(75.0)))
    assert stats.word_count == 1


# --- quality_flag ------------------------------------------------------------

def test_flag_good_at_threshold():
    assert quality_flag(TsvStats(word_count=50, mean_conf=80.0)) == "good"

def test_flag_fair_between_thresholds():
    assert quality_flag(TsvStats(word_count=50, mean_conf=65.0)) == "fair"

def test_flag_review_below_fair():
    assert quality_flag(TsvStats(word_count=50, mean_conf=59.9)) == "review"

def test_flag_empty_when_no_words():
    assert quality_flag(TsvStats(word_count=0, mean_conf=0.0)) == "empty"
