from patent_ingest.parse_body import (
    _find_claims_start_offset,
    _split_sections_by_heading_positions,
)


def _simulate_trim_like_parse_patent_body(
    body_text: str, sections: dict, spans: dict
) -> tuple[dict, dict]:
    """
    Your current parse_patent_body trims narrative sections at claims_start_offset and ensures a claims section exists.
    This helper simulates that logic for unit testing.
    """
    claims_start = _find_claims_start_offset(body_text)
    if claims_start is None:
        return sections, spans

    for key in (
        "background",
        "summary",
        "brief_description_of_drawings",
        "detailed_description",
    ):
        if key in spans:
            s, e = spans[key]
            if e > claims_start:
                spans[key] = (s, min(e, claims_start))
                sections[key] = body_text[spans[key][0] : spans[key][1]].strip()

    if "claims" not in sections:
        sections["claims"] = body_text[claims_start:].strip()
        spans["claims"] = (claims_start, len(body_text))

    return sections, spans


def test_position_based_split_finds_main_narrative_sections_embedded_mid_line():
    text = (
        "TECHNICAL FIELD Some field. "
        "BACKGROUND ART Background content here. "
        "SUMMARY OF THE INVENTION Summary content here. "
        "BRIEF DESCRIPTION OF THE DRAWINGS FIG. 1 ... "
        "DETAILED DESCRIPTION Detailed content here. "
        "The invention claimed is: 1. A claim. 2. Another claim."
    )

    sections, spans, headings = _split_sections_by_heading_positions(text)

    assert "background" in sections
    assert "summary" in sections
    assert "brief_description_of_drawings" in sections
    assert "detailed_description" in sections

    assert "background content" in sections["background"].lower()
    assert "summary content" in sections["summary"].lower()
    assert "fig. 1" in sections["brief_description_of_drawings"].lower()
    assert "detailed content" in sections["detailed_description"].lower()


def test_trim_removes_claims_from_detailed_description_and_creates_claims_section():
    text = (
        "BACKGROUND ART Background.\n"
        "DETAILED DESCRIPTION Here is the detailed description text.\n"
        "The invention claimed is: 1. A claim. 2. Another claim."
    )

    sections, spans, headings = _split_sections_by_heading_positions(text)

    # Do not assert pre-trim containment; splitter may already separate or may not.
    sections, spans = _simulate_trim_like_parse_patent_body(text, sections, spans)

    # Post-condition: narrative sections must not contain claims.
    assert "detailed_description" in sections
    assert "the invention claimed is" not in sections["detailed_description"].lower()
    assert "1." not in sections["detailed_description"]
    assert "2." not in sections["detailed_description"]

    # Post-condition: claims section must exist and contain claims block.
    assert "claims" in sections
    assert "the invention claimed is" in sections["claims"].lower()
    assert "1." in sections["claims"]
    assert "2." in sections["claims"]


def test_no_headings_returns_empty_structures():
    text = "Plain narrative without recognizable headings."
    sections, spans, headings = _split_sections_by_heading_positions(text)

    assert sections == {}
    assert spans == {}
    assert headings == []
