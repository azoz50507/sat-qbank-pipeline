"""Unit tests for payload validation and helpers (qbank.downloader)."""

from qbank.downloader import MIN_SIZE_BYTES, detect_type, safe_filename, validate_payload

PADDING = b"x" * MIN_SIZE_BYTES  # lifts payloads over the minimum-size gate


# --- magic-byte detection ---------------------------------------------------

def test_detects_pdf_magic():
    assert detect_type(b"%PDF-1.7 rest of file") == "pdf"

def test_detects_html_doctype():
    assert detect_type(b"<!DOCTYPE html><html><body>404</body></html>") == "html"

def test_detects_html_tag_with_leading_whitespace():
    assert detect_type(b"   \n<html lang='en'>...") == "html"

def test_detects_json():
    assert detect_type(b'{"error": "not found"}') == "json"

def test_unknown_binary():
    assert detect_type(b"\x00\x01\x02\x03 binary soup") == "unknown"


# --- payload validation -----------------------------------------------------

def test_valid_pdf_passes():
    ok, detected, detail = validate_payload(b"%PDF-1.4\n" + PADDING, expected="pdf")
    assert ok and detected == "pdf"

def test_tiny_pdf_rejected_as_placeholder():
    ok, _, detail = validate_payload(b"%PDF-1.4 tiny", expected="pdf")
    assert not ok and "too small" in detail

def test_html_error_page_rejected_even_if_large():
    ok, detected, detail = validate_payload(b"<!DOCTYPE html>" + PADDING, expected="pdf")
    assert not ok and detected == "html" and "error/placeholder" in detail

def test_wrong_type_rejected():
    ok, detected, detail = validate_payload(b'{"ok": true}' + PADDING, expected="pdf")
    assert not ok and "expected PDF magic bytes" in detail


# --- filename hygiene -------------------------------------------------------

def test_safe_filename_unquotes_and_sanitizes():
    assert safe_filename("Scholastic%20Aptitude%20Test%20(1926).pdf") == \
        "Scholastic_Aptitude_Test__1926_.pdf"

def test_safe_filename_strips_path_separators():
    assert "/" not in safe_filename("a/b\\c.pdf")
    assert "\\" not in safe_filename("a/b\\c.pdf")
