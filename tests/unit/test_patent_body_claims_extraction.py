from patent_ingest.parse_body import (
    _CLAIMS_ANCHOR_RX,
    _extract_claims_block,
    _find_claims_region_tail,
    _find_claims_start_offset,
    _parse_claims_from_block,
)


def test_claims_anchor_regex_matches_common_variants():
    samples = [
        "What is claimed is: 1. A claim.",
        "The invention claimed is: 1. A claim.",
        "I/We claim: 1. A claim.",
        "i / we claim: 1. A claim.",
    ]
    for s in samples:
        assert _CLAIMS_ANCHOR_RX.search(s) is not None


def test_extract_claims_block_uses_anchor_and_parses_multiple_claims():
    body = (
        "Some narrative text... BACKGROUND ART ... "
        "The invention claimed is: "
        "1. A first claim comprising something. "
        "2. The system of claim 1, wherein something. "
        "3. A method comprising doing a thing."
    )
    qa = {"warnings": [], "info": {}}
    claims_block = _extract_claims_block(body, sections={}, qa=qa)

    assert qa["info"]["claims_extraction_method"] == "anchor"
    assert claims_block.startswith("1.")
    claims = _parse_claims_from_block(claims_block)

    assert len(claims) == 3
    assert claims[0].startswith("1.")
    assert claims[1].startswith("2.")
    assert claims[2].startswith("3.")


def test_parse_claims_when_numbers_are_space_separated_not_newlines():
    # Compatible with your regex: requires capital letter after "N."
    block = (
        "1. A first claim comprising something. "
        "2. The system of claim 1, wherein something. "
        "3. The system of claim 2, wherein something else."
    )
    claims = _parse_claims_from_block(block)
    assert len(claims) == 3
    assert claims[0].startswith("1.")
    assert claims[1].startswith("2.")
    assert claims[2].startswith("3.")


def test_find_claims_start_offset_prefers_anchor():
    text = (
        "Some narrative... "
        "The invention claimed is: "
        "1. A first claim. 2. The system of claim 1, wherein ..."
    )
    off = _find_claims_start_offset(text)
    assert off is not None
    assert text[off : off + 30].lower().startswith("the invention claimed is")


def test_tail_region_finder_avoids_header_false_positive_by_tail_window():
    # Ensure header is in the first 60% and claims are in the tail.
    header = "US 9,999,999 B2 1. SYSTEM FOR SOMETHING (TITLE HEADER) " * 50
    filler = "Some additional body text without claim-like numbering. " * 200

    tail_claims = (
        "\n\nMore narrative near end...\n"
        "1. A first claim comprising a thing.\n"
        "2. The system of claim 1, wherein the thing is improved.\n"
        "3. The system of claim 2, wherein the improvement is significant.\n"
        "4. The system of claim 3, wherein the device further comprises a widget.\n"
        "5. The system of claim 4, wherein the widget is configured to operate.\n"
        "6. The system of claim 5, wherein operation includes steps.\n"
    )

    text = header + filler + tail_claims

    region = _find_claims_region_tail(text)
    assert region is not None
    start, end, diag = region

    # The found region should be past the midpoint because we only search in the tail
    assert start > int(len(text) * 0.5)
    assert diag["claim_starts_in_window"] >= 5

    # And parsing from the extracted block should yield multiple claims
    qa = {"warnings": [], "info": {}}
    claims_block = _extract_claims_block(text, sections={}, qa=qa)
    claims = _parse_claims_from_block(claims_block)
    assert len(claims) >= 6
