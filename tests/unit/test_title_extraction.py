"""Unit tests for title extraction (front_matter/title.py)."""

import pytest
from patent_ingest.front_matter.title import extract_title
from patent_ingest.front_matter.inid import parse_inid_blocks_raw
from conftest import mp, assert_no_errors, assert_has_error, assert_has_warning


def test_title_from_inid_54_clean(diag, linconf):
    """Test extracting title from INID(54) marker."""
    doc = mp(
        ("(54) METHOD AND APPARATUS FOR NETWORK COMMUNICATION", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    assert out.value == "METHOD AND APPARATUS FOR NETWORK COMMUNICATION"
    assert out.meta["source"] == "inid"
    assert out.meta["inid_code"] == "54"
    assert_no_errors(diag)


def test_title_from_inid_54_with_newlines(diag, linconf):
    """Test title extraction with newlines in the title."""
    doc = mp(
        (
            "(54) METHOD AND APPARATUS\n"
            "     FOR NETWORK\n"
            "     COMMUNICATION\n"
            "(73) Assignee: Example Corp",
            ""
        ),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    # Should normalize whitespace/newlines
    assert "METHOD AND APPARATUS" in out.value
    assert "NETWORK" in out.value
    assert "COMMUNICATION" in out.value
    assert "Assignee" not in out.value  # Should stop at next INID
    assert_no_errors(diag)


def test_title_stops_at_abstract_heading(diag, linconf):
    """Test that title stops at ABSTRACT heading."""
    doc = mp(
        (
            "(54) METHOD FOR DATA PROCESSING\n"
            "ABSTRACT\n"
            "This is the abstract text.",
            ""
        ),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    assert out.value == "METHOD FOR DATA PROCESSING"
    assert "ABSTRACT" not in out.value
    assert "abstract text" not in out.value
    assert_no_errors(diag)


def test_title_stops_at_references_heading(diag, linconf):
    """Test that title stops at REFERENCES CITED heading."""
    doc = mp(
        (
            "(54) NETWORK ROUTING SYSTEM\n"
            "REFERENCES CITED\n"
            "U.S. PATENT DOCUMENTS",
            ""
        ),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    assert out.value == "NETWORK ROUTING SYSTEM"
    assert "REFERENCES" not in out.value
    assert_no_errors(diag)


def test_title_with_punctuation(diag, linconf):
    """Test title with various punctuation marks."""
    doc = mp(
        ("(54) METHOD  ,  SYSTEM  ,  AND   DEVICE", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    # normalize_punctuation_spacing should clean up spacing around commas
    assert "METHOD, SYSTEM, AND DEVICE" in out.value or "METHOD , SYSTEM , AND DEVICE" in out.value


def test_title_too_short_rejected(diag, linconf):
    """Test that titles that are too short are rejected."""
    doc = mp(
        ("(54) AB", ""),  # Only 2 characters
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    # Should fail validation and attempt fallback
    assert out is None
    assert_has_error(diag, "title.missing")


def test_title_just_inid_marker_rejected(diag, linconf):
    """Test that a title containing only an INID marker is rejected."""
    doc = mp(
        ("(54) (73)", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    assert out is None
    assert_has_error(diag, "title.missing")


def test_title_fallback_inid_marker(diag, linconf):
    """Test fallback extraction when INID(54) is malformed but pattern matches."""
    doc = mp(
        (
            "United States Patent\n"
            "(54) SYSTEM FOR REAL-TIME DATA ANALYSIS\n"
            "(75) Inventors: John Smith",
            ""
        ),
    )
    # Simulate INID parsing failure by passing empty dict
    inids = {}
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    assert "SYSTEM FOR REAL-TIME DATA ANALYSIS" in out.value
    assert "Inventors" not in out.value


def test_title_fallback_label_pattern(diag, linconf):
    """Test fallback extraction using 'Title:' label."""
    doc = mp(
        (
            "United States Patent\n"
            "Title: APPARATUS FOR WIRELESS COMMUNICATION\n"
            "Inventor: Jane Doe",
            ""
        ),
    )
    inids = {}  # No INID blocks
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    assert "APPARATUS FOR WIRELESS COMMUNICATION" in out.value
    # Note: This may capture more than expected with the regex
    # The actual behavior depends on the pattern


def test_title_missing_all_strategies(diag, linconf):
    """Test error when no title can be found by any strategy."""
    doc = mp(
        (
            "United States Patent\n"
            "Smith et al.\n"
            "No title here!",
            ""
        ),
    )
    inids = {}
    out = extract_title(doc, inids, diag, **linconf)

    assert out is None
    assert_has_error(diag, "title.missing")


def test_title_multiline_with_proper_formatting(diag, linconf):
    """Test title that spans multiple lines with proper formatting."""
    doc = mp(
        (
            "(54) METHODS AND SYSTEMS FOR\n"
            "     DISTRIBUTED COMPUTING IN\n"
            "     CLOUD ENVIRONMENTS\n"
            "(75) Inventors:",
            ""
        ),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    assert "METHODS AND SYSTEMS" in out.value
    assert "DISTRIBUTED COMPUTING" in out.value
    assert "CLOUD ENVIRONMENTS" in out.value
    assert "Inventors" not in out.value
    assert_no_errors(diag)


def test_title_case_insensitive_stop_words(diag, linconf):
    """Test that stop words work case-insensitively."""
    doc = mp(
        (
            "(54) DATA PROCESSING METHOD\n"
            "abstract\n"
            "Some text here",
            ""
        ),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_title(doc, inids, diag, **linconf)

    assert out is not None
    assert "DATA PROCESSING METHOD" == out.value.strip()
    assert "abstract" not in out.value.lower()
    assert "Some text" not in out.value
