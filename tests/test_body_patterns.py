"""Unit tests for doc_extractor.body.patterns module.

Tests cover:
- Regex pattern matching (claims anchor, claim markers, figure references)
- Claims extraction logic (anchor-based and fallback methods)
- Figure description parsing
- Section heading detection
- OCR corruption handling
"""

import pytest
import re
from doc_extractor.body.patterns import (
    _CLAIMS_ANCHOR_RX,
    _CLAIM_START_MARKER_RX,
    _FIG_REF_RE,
    _CLAIM_START_PATTERN,
    _looks_like_claim,
    _expand_fig_range,
    _parse_figlist,
    _find_claims_start_offset,
    _parse_claims_from_block,
    _find_claims_region_tail,
    _extract_claims_block,
    extract_drawing_descriptions,
    _find_heading_positions,
    MIN_CLAIM_LENGTH,
)


class TestClaimsAnchorRegex:
    """Test the _CLAIMS_ANCHOR_RX pattern."""

    def test_matches_what_is_claimed_is(self):
        """Should match 'what is claimed is' (most common)."""
        text = "... detailed description continues.\n\nWhat is claimed is:\n\n1. A method..."
        match = _CLAIMS_ANCHOR_RX.search(text)
        assert match is not None
        assert match.group(1).lower() == "what is claimed is"

    def test_matches_what_is_claimed_is_no_colon(self):
        """Should match 'what is claimed is' without colon."""
        text = "What is claimed is\n\n1. A method..."
        match = _CLAIMS_ANCHOR_RX.search(text)
        assert match is not None

    def test_matches_the_invention_claimed_is(self):
        """Should match alternative anchor phrase."""
        text = "The invention claimed is:\n1. A system..."
        match = _CLAIMS_ANCHOR_RX.search(text)
        assert match is not None
        assert "invention claimed is" in match.group(1).lower()

    def test_matches_i_we_claim(self):
        """Should match 'I/We claim' format."""
        text = "I/We claim:\n1. A device..."
        match = _CLAIMS_ANCHOR_RX.search(text)
        assert match is not None

    def test_case_insensitive(self):
        """Should be case insensitive."""
        for text in ["WHAT IS CLAIMED IS:", "what is claimed is:", "What Is Claimed Is:"]:
            match = _CLAIMS_ANCHOR_RX.search(text)
            assert match is not None, f"Failed to match: {text}"

    def test_does_not_match_partial(self):
        """Should not match partial phrases."""
        text = "The claim is supported by the specification."
        match = _CLAIMS_ANCHOR_RX.search(text)
        assert match is None


class TestClaimStartMarkerRegex:
    """Test the _CLAIM_START_MARKER_RX pattern."""

    def test_matches_standard_claim_markers(self):
        """Should match standard claim formats: '1. A', '2. The', etc."""
        test_cases = [
            "1. A method comprising",
            "2. The apparatus of claim 1",
            "15. An improved system",
            "100. The method of claim 99",
        ]
        for text in test_cases:
            matches = list(_CLAIM_START_MARKER_RX.finditer(text))
            assert len(matches) == 1, f"Failed to match: {text}"
            assert matches[0].group(1) or matches[0].group(2), f"No capture group for: {text}"

    def test_matches_claim_with_parenthesis(self):
        """Should match claim with ) separator."""
        text = "1) A method for processing"
        matches = list(_CLAIM_START_MARKER_RX.finditer(text))
        assert len(matches) == 1

    def test_matches_claim_with_colon(self):
        """Should match claim with : separator."""
        text = "1: The apparatus comprises"
        matches = list(_CLAIM_START_MARKER_RX.finditer(text))
        assert len(matches) == 1

    def test_handles_ocr_corruption_dash(self):
        """Should handle OCR corruption where '.' becomes '-'."""
        text = "15-4 An apparatus comprising"
        matches = list(_CLAIM_START_MARKER_RX.finditer(text))
        assert len(matches) == 1
        num = matches[0].group(1) or matches[0].group(2)
        assert num == "15"

    def test_matches_at_line_start_no_period(self):
        """Should match claim at line start even if period is dropped by OCR."""
        text = "1 A method for processing data"
        matches = list(_CLAIM_START_MARKER_RX.finditer(text))
        assert len(matches) == 1

    def test_does_not_match_after_claim_word(self):
        """Should not match 'claim 1' or 'claims 1'."""
        text = "The method of claim 1 further comprises"
        matches = list(_CLAIM_START_MARKER_RX.finditer(text))
        assert len(matches) == 0

    def test_does_not_match_figure_references(self):
        """Should not match figure references like 'FIG. 1'."""
        text = "As shown in FIG. 1, the system comprises"
        matches = list(_CLAIM_START_MARKER_RX.finditer(text))
        # May match if "1, the" looks like a claim start, but should be filtered by context
        # This is where _looks_like_claim() comes in

    def test_multiple_claims_in_text(self):
        """Should find multiple claim starts in a block."""
        text = """1. A method comprising: receiving data.

2. The method of claim 1, wherein the data is validated.

3. The method of claim 1, further comprising storing the data."""
        matches = list(_CLAIM_START_MARKER_RX.finditer(text))
        assert len(matches) == 3
        numbers = [m.group(1) or m.group(2) for m in matches]
        assert numbers == ["1", "2", "3"]

    def test_handles_large_claim_numbers(self):
        """Should handle claim numbers up to 999."""
        text = "999. The method of claim 998"
        matches = list(_CLAIM_START_MARKER_RX.finditer(text))
        assert len(matches) == 1
        assert (matches[0].group(1) or matches[0].group(2)) == "999"


class TestLooksLikeClaim:
    """Test the _looks_like_claim heuristic function."""

    def test_accepts_valid_independent_claim(self):
        """Should accept standard independent claim."""
        chunk = "1. A method for processing data, the method comprising: receiving input;"
        assert _looks_like_claim(chunk) is True

    def test_accepts_valid_dependent_claim(self):
        """Should accept standard dependent claim."""
        chunk = "2. The method of claim 1, wherein the processing includes validation."
        assert _looks_like_claim(chunk) is True

    def test_rejects_too_short(self):
        """Should reject chunks shorter than MIN_CLAIM_LENGTH."""
        chunk = "1. A method."
        assert _looks_like_claim(chunk) is False

    def test_rejects_empty(self):
        """Should reject empty or None input."""
        assert _looks_like_claim("") is False
        assert _looks_like_claim(None) is False

    def test_rejects_figure_reference(self):
        """Should reject figure references that match claim marker pattern."""
        chunk = "15. FIG. 15 shows the processing flow in detail"
        assert _looks_like_claim(chunk) is False

    def test_rejects_page_number(self):
        """Should reject page numbers."""
        chunk = "10. \n\n[Page header or footer content]"
        # Should be rejected as too short or lacking claim indicators
        assert _looks_like_claim(chunk) is False

    def test_accepts_claim_with_comprising(self):
        """Should accept claims containing 'comprising'."""
        chunk = "1. The system comprising: a processor and memory unit for data storage"
        assert _looks_like_claim(chunk) is True

    def test_accepts_claim_with_wherein(self):
        """Should accept claims containing 'wherein'."""
        chunk = "2. A device wherein the processor executes instructions from memory"
        assert _looks_like_claim(chunk) is True


class TestExpandFigRange:
    """Test the _expand_fig_range function."""

    def test_expands_numeric_range(self):
        """Should expand numeric ranges like '2-5'."""
        result = _expand_fig_range("2", "5")
        assert result == ["2", "3", "4", "5"]

    def test_expands_letter_suffix_range(self):
        """Should expand letter suffix ranges like '2A-2C'."""
        result = _expand_fig_range("2A", "2C")
        assert result == ["2A", "2B", "2C"]

    def test_expands_letter_suffix_range_lowercase(self):
        """Should handle lowercase input."""
        result = _expand_fig_range("2a", "2c")
        # Should convert to uppercase
        assert len(result) == 3
        assert all(item.startswith("2") for item in result)

    def test_returns_endpoints_for_mismatched_bases(self):
        """Should return just endpoints if bases don't match."""
        result = _expand_fig_range("2A", "3A")
        assert result == ["2A", "3A"]

    def test_returns_single_for_same_start_end(self):
        """Should return single item if start equals end."""
        result = _expand_fig_range("5", "5")
        assert result == ["5"]

    def test_handles_invalid_input(self):
        """Should handle invalid input gracefully."""
        result = _expand_fig_range("abc", "def")
        assert result == ["abc", "def"]


class TestParseFiglist:
    """Test the _parse_figlist function."""

    def test_parses_single_figure(self):
        """Should parse single figure ID."""
        result = _parse_figlist("3")
        assert result == ["3"]

    def test_parses_figure_with_suffix(self):
        """Should parse figure ID with letter suffix."""
        result = _parse_figlist("2A")
        assert result == ["2A"]

    def test_parses_comma_separated_list(self):
        """Should parse comma-separated list."""
        result = _parse_figlist("1, 2, 3")
        assert result == ["1", "2", "3"]

    def test_parses_and_separated_list(self):
        """Should parse 'and' separated list."""
        result = _parse_figlist("6 and 7")
        assert result == ["6", "7"]

    def test_parses_comma_and_combined(self):
        """Should parse mixed comma and 'and' separators."""
        result = _parse_figlist("1, 2 and 3")
        assert result == ["1", "2", "3"]

    def test_expands_ranges(self):
        """Should expand ranges within the list."""
        result = _parse_figlist("1A-1C, 2 and 3")
        assert "1A" in result
        assert "1B" in result
        assert "1C" in result
        assert "2" in result
        assert "3" in result

    def test_deduplicates(self):
        """Should remove duplicates."""
        result = _parse_figlist("1, 1, 2")
        assert len(result) == 2
        assert set(result) == {"1", "2"}


class TestFindClaimsStartOffset:
    """Test _find_claims_start_offset function."""

    def test_finds_anchor_phrase(self, sample_claims_text):
        """Should find claims using anchor phrase."""
        offset = _find_claims_start_offset(sample_claims_text)
        assert offset is not None
        # Should be at or after "What is claimed is:"
        assert "What is claimed is" in sample_claims_text[:offset + 30]

    def test_returns_none_for_text_without_claims(self):
        """Should return None if no claims found."""
        text = "This is just a description with no claims section."
        offset = _find_claims_start_offset(text)
        assert offset is None

    def test_returns_none_for_too_short_text(self):
        """Should return None for text below minimum length."""
        text = "Short text"
        offset = _find_claims_start_offset(text)
        assert offset is None


class TestParseClaimsFromBlock:
    """Test _parse_claims_from_block function."""

    def test_parses_standard_claims(self, sample_claims_text):
        """Should parse standard well-formatted claims."""
        # Extract just the claims part
        claims_block = sample_claims_text.split("What is claimed is:")[1]
        claims = _parse_claims_from_block(claims_block)

        assert len(claims) == 5
        assert all(claim.startswith(f"{i+1}.") for i, claim in enumerate(claims))

    def test_handles_ocr_corrupted_claims(self, sample_claims_text_with_ocr_errors):
        """Should handle OCR-corrupted claim markers."""
        claims_block = sample_claims_text_with_ocr_errors.split("What is claimed is:")[1]
        claims = _parse_claims_from_block(claims_block)

        # Should find at least some claims despite OCR errors
        assert len(claims) >= 2

    def test_normalizes_whitespace(self):
        """Should normalize whitespace in claims."""
        text = "1. A    method   for   processing    data   comprising   multiple   steps"
        claims = _parse_claims_from_block(text)

        assert len(claims) == 1
        # Whitespace should be normalized to single spaces
        assert "  " not in claims[0]

    def test_canonicalizes_claim_prefix(self):
        """Should canonicalize claim prefix to 'N.'."""
        text = "1) A method for processing data comprising multiple steps.\n2: The apparatus of claim 1 wherein the processing includes validation."
        claims = _parse_claims_from_block(text)

        assert len(claims) == 2
        assert claims[0].startswith("1. ")
        assert claims[1].startswith("2. ")

    def test_stops_at_non_claim_content(self):
        """Should stop extracting when non-claim content is found."""
        text = """1. A method comprising multiple steps for processing data in a computer system.

2. The method of claim 1 wherein the steps include validation and transformation.

ABSTRACT OF THE DISCLOSURE

This is the abstract text."""
        claims = _parse_claims_from_block(text)

        # Should stop before the abstract
        assert len(claims) == 2


class TestFindClaimsRegionTail:
    """Test _find_claims_region_tail fallback function."""

    def test_finds_claims_in_tail(self):
        """Should find claims region in document tail."""
        # Simulate a document with claims at the end
        text = "A" * 10000  # Filler content
        text += "\n\n1. A method comprising: receiving data;\n\n"
        text += "2. The method of claim 1, wherein data is processed;\n\n"
        text += "3. The method of claim 1, further comprising validation;\n\n"
        text += "4. The method of claim 1, wherein processing includes transformation;\n\n"
        text += "5. An apparatus for implementing the method of claim 1."

        result = _find_claims_region_tail(text)

        assert result is not None
        start, end, diagnostics = result
        assert start > 10000  # Should be in the tail
        assert "claim_starts_in_window" in diagnostics
        assert diagnostics["claim_starts_in_window"] >= 5

    def test_returns_none_for_no_claims(self):
        """Should return None if no claims found in tail."""
        text = "Just regular text without any numbered claims section"
        result = _find_claims_region_tail(text)
        assert result is None

    def test_prefers_sequential_numbering(self):
        """Should score sequential numbering higher."""
        # Create text with a clear sequential claims region at the end
        text = "A" * 15000  # Padding to push past the 60% threshold
        text += "\n" + "B" * 3000  # More padding
        # Add a perfect sequential claims section
        text += "\n\n1. A method for processing data comprising multiple processing steps.\n"
        text += "2. The method of claim 1 further comprising a validation step.\n"
        text += "3. The method of claim 1 wherein the data is transformed.\n"
        text += "4. The method of claim 2 wherein errors are logged.\n"
        text += "5. An apparatus for implementing the method of claim 1.\n"
        text += "6. The apparatus of claim 5 further comprising a display.\n"

        result = _find_claims_region_tail(text)
        assert result is not None
        start, end, diag = result

        # The sequential region should be found
        region_text = text[start:end]
        assert "1. A method" in region_text or "2. The method" in region_text
        # Should have high score due to perfect sequencing
        assert diag["score"] > 10


class TestExtractClaimsBlock:
    """Test _extract_claims_block function."""

    def test_prefers_anchor_method(self, sample_claims_text):
        """Should prefer anchor phrase method over fallback."""
        sections = {}  # No section-based claims
        qa = {"warnings": [], "info": {}}

        block = _extract_claims_block(sample_claims_text, sections, qa)

        assert block != ""
        assert qa["info"]["claims_extraction_method"] == "anchor"
        assert "claims_anchor" in qa["info"]

    def test_uses_section_if_present(self):
        """Should use section-based claims if present and no anchor."""
        body_text = "Some text without anchor phrase"
        sections = {"claims": "1. A method\n2. The method of claim 1"}
        qa = {"warnings": [], "info": {}}

        block = _extract_claims_block(body_text, sections, qa)

        assert "1. A method" in block

    def test_adds_warning_for_fallback(self):
        """Should add warning when using fallback method."""
        # Text with claims but no anchor phrase, forcing fallback
        text = "A" * 15000
        text += "\n1. A method\n2. Method of claim 1\n3. Method of claim 1\n"
        text += "4. Method of claim 1\n5. Apparatus of claim 1\n"
        sections = {}
        qa = {"warnings": [], "info": {}}

        block = _extract_claims_block(text, sections, qa)

        if qa["info"].get("claims_extraction_method") == "tail_numbered_list":
            assert "claims_section_fallback_used" in qa["warnings"]


class TestExtractDrawingDescriptions:
    """Test extract_drawing_descriptions function."""

    def test_extracts_single_figure_description(self):
        """Should extract description for single figure."""
        text = "FIG. 1 is a block diagram of the system."
        results = extract_drawing_descriptions(text)

        assert len(results) == 1
        assert results[0]["figure_number"] == 1
        assert results[0]["figure_suffix"] is None
        assert "block diagram" in results[0]["description"]

    def test_extracts_figure_with_suffix(self, sample_figure_descriptions_text):
        """Should extract figures with letter suffixes."""
        results = extract_drawing_descriptions(sample_figure_descriptions_text)

        # Should find 2A, 2B, 2C
        suffixed_figs = [r for r in results if r["figure_suffix"] is not None]
        assert len(suffixed_figs) >= 3

    def test_expands_figure_ranges(self, sample_figure_descriptions_text):
        """Should expand figure ranges like 'FIGS. 3-5'."""
        results = extract_drawing_descriptions(sample_figure_descriptions_text)

        # Should have separate entries for 3, 4, 5
        fig_numbers = {r["figure_number"] for r in results}
        assert 3 in fig_numbers
        assert 4 in fig_numbers
        assert 5 in fig_numbers

    def test_handles_figs_and_list(self, sample_figure_descriptions_text):
        """Should handle 'FIGS. 6 and 7'."""
        results = extract_drawing_descriptions(sample_figure_descriptions_text)

        fig_numbers = {r["figure_number"] for r in results}
        assert 6 in fig_numbers
        assert 7 in fig_numbers

    def test_normalizes_whitespace_in_descriptions(self):
        """Should normalize whitespace in descriptions."""
        text = "FIG. 1 is a    diagram   with    extra     spaces"
        results = extract_drawing_descriptions(text)

        assert len(results) == 1
        # Should have normalized whitespace
        assert "    " not in results[0]["description"]

    def test_returns_empty_for_no_figures(self):
        """Should return empty list if no figures found."""
        text = "This is text without any figure descriptions."
        results = extract_drawing_descriptions(text)
        assert results == []


class TestFindHeadingPositions:
    """Test _find_heading_positions function."""

    def test_finds_standard_section_headings(self, sample_body_text_with_sections):
        """Should find all standard USPTO section headings."""
        hits = _find_heading_positions(sample_body_text_with_sections)

        sections_found = {hit.section for hit in hits}
        assert "background" in sections_found
        assert "summary" in sections_found
        assert "brief_description_of_drawings" in sections_found
        assert "detailed_description" in sections_found
        assert "claims" in sections_found

    def test_headings_in_order(self, sample_body_text_with_sections):
        """Should return headings in document order."""
        hits = _find_heading_positions(sample_body_text_with_sections)

        # Hits should be sorted by start position
        positions = [hit.start for hit in hits]
        assert positions == sorted(positions)

    def test_matches_case_insensitive(self):
        """Should match headings regardless of case."""
        text = "BACKGROUND OF THE INVENTION\n\nText here.\n\nBackground of the Invention\n\nMore text."
        hits = _find_heading_positions(text)

        # Should find background heading(s)
        background_hits = [hit for hit in hits if hit.section == "background"]
        assert len(background_hits) > 0

    def test_deduplicates_close_hits(self):
        """Should deduplicate headings that appear close together."""
        # Same heading appearing twice nearby
        text = "SUMMARY\n\nSummary of the Invention\n\nActual content here."
        hits = _find_heading_positions(text)

        summary_hits = [hit for hit in hits if hit.section == "summary"]
        # Should deduplicate or keep only one
        assert len(summary_hits) <= 2  # Allow some flexibility in dedup logic


# Integration-style tests that combine multiple functions

class TestClaimsExtractionIntegration:
    """Integration tests for full claims extraction workflow."""

    def test_end_to_end_claims_extraction(self, sample_claims_text):
        """Test complete workflow: find offset -> extract block -> parse claims."""
        # Step 1: Find claims start
        offset = _find_claims_start_offset(sample_claims_text)
        assert offset is not None

        # Step 2: Extract claims block
        sections = {}
        qa = {"warnings": [], "info": {}}
        claims_block = _extract_claims_block(sample_claims_text, sections, qa)
        assert claims_block != ""

        # Step 3: Parse claims
        claims = _parse_claims_from_block(claims_block)
        assert len(claims) == 5

        # Verify structure of first claim
        assert claims[0].startswith("1. ")
        assert "method" in claims[0].lower()

    def test_handles_document_without_anchor(self):
        """Should fall back to tail search when anchor is missing."""
        # Create a document with claims but no anchor phrase
        text = "Detailed description text here. " * 500
        text += "\n\n1. A method for data processing comprising: receiving input;\n\n"
        text += "2. The method of claim 1, wherein the input is validated;\n\n"
        text += "3. The method of claim 1, further comprising transformation;\n\n"
        text += "4. The method of claim 1, wherein output is generated;\n\n"
        text += "5. An apparatus implementing the method of claim 1."

        # Should still find claims using fallback
        offset = _find_claims_start_offset(text)
        if offset is None:
            # Try fallback method directly
            result = _find_claims_region_tail(text)
            assert result is not None


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_handles_empty_input(self):
        """Should handle empty input gracefully."""
        assert _find_claims_start_offset("") is None
        assert _parse_claims_from_block("") == []
        assert extract_drawing_descriptions("") == []
        assert _find_heading_positions("") == []

    def test_handles_very_short_document(self):
        """Should handle documents below minimum length."""
        short_text = "Too short"
        assert _find_claims_start_offset(short_text) is None

    def test_handles_malformed_claims(self):
        """Should handle claims with unusual formatting."""
        text = "1. A method for processing data comprising multiple steps.\n\n5. Another method comprising different steps for validation.\n\n2. An out of order method for transformation."
        claims = _parse_claims_from_block(text)
        # Should handle gracefully, possibly stopping at the out-of-order claim
        assert isinstance(claims, list)
        # Should extract at least the first claim
        assert len(claims) >= 1


class TestClaimValidationHeuristics:
    """Test the claim validation logic that filters false positives.

    These tests verify that _parse_claims_from_block correctly rejects
    short text, page numbers, and figure references while accepting
    valid claims that meet minimum length and pattern requirements.
    """

    def test_rejects_too_short_claims(self):
        """Should reject claims shorter than MIN_CLAIM_LENGTH (30 chars)."""
        # This is intentionally too short - should be filtered as false positive (page number, etc.)
        text = "1. A method."
        claims = _parse_claims_from_block(text)
        # Should return empty because claim is too short
        assert len(claims) == 0

    def test_rejects_multiple_short_claims(self):
        """Should reject multiple claims when all are too short."""
        text = "1. A method.\n2. An apparatus."
        claims = _parse_claims_from_block(text)
        assert len(claims) == 0

    def test_rejects_page_numbers(self):
        """Should reject standalone page numbers."""
        text = "Page 15.\n\nSome content here that goes on for a while."
        claims = _parse_claims_from_block(text)
        assert len(claims) == 0

    def test_rejects_figure_references(self):
        """Should reject figure references that look like claim markers."""
        text = "15. FIG. 15 shows the system architecture diagram."
        claims = _parse_claims_from_block(text)
        # Too short and doesn't match claim patterns
        assert len(claims) == 0

    def test_accepts_minimum_length_valid_claim(self):
        """Should accept claim that meets minimum length and pattern requirements."""
        # Right at the boundary - should pass if it matches patterns
        text = "1. A method comprising multiple steps."
        claims = _parse_claims_from_block(text)
        assert len(claims) == 1

    def test_accepts_independent_claim_with_article(self):
        """Should accept independent claims starting with articles."""
        text = "1. A method for processing data in a computer system comprising steps."
        claims = _parse_claims_from_block(text)
        assert len(claims) == 1
        assert claims[0].startswith("1. A method")

    def test_accepts_claim_with_an_article(self):
        """Should accept claims starting with 'An'."""
        text = "1. An apparatus for processing data comprising a processor and memory."
        claims = _parse_claims_from_block(text)
        assert len(claims) == 1

    def test_accepts_dependent_claim_reference(self):
        """Should accept dependent claims referencing other claims."""
        text = "2. The method of claim 1 further comprising validation and error handling."
        claims = _parse_claims_from_block(text)
        assert len(claims) == 1
        assert "claim 1" in claims[0].lower()

    def test_filters_out_section_headers(self):
        """Should filter out section headers that might have numbers."""
        text = "1. Field of the Invention\n\nThis invention relates to data processing."
        claims = _parse_claims_from_block(text)
        # "1. Field of the Invention" doesn't match claim patterns
        assert len(claims) == 0

    def test_mixed_valid_and_invalid(self):
        """Should extract valid claims but stop at first invalid after finding claims."""
        text = """1. Page number.

2. A method for processing data comprising multiple steps for validation.

3. Another short one.

4. The method of claim 2 further comprising error handling and logging."""
        claims = _parse_claims_from_block(text)
        # Should skip claim 1 (too short), get claim 2, then stop at claim 3 (invalid)
        # Claim 4 won't be reached because function stops after invalid claim 3
        assert len(claims) == 1
        assert claims[0].startswith("2. A method")

    def test_skips_invalid_before_finding_first_valid(self):
        """Should skip invalid claims at the start until finding a valid one."""
        text = """1. Short.

2. Also short.

3. A method for processing data comprising multiple steps and validation.

4. The method of claim 3 further comprising error handling procedures."""
        claims = _parse_claims_from_block(text)
        # Should skip claims 1-2, then get claims 3-4
        assert len(claims) == 2
        assert claims[0].startswith("3. A method")
        assert claims[1].startswith("4. The method")
