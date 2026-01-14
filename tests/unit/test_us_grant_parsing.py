from patent_ingest.parse_front_page import extract_cited_us_patents_from_refs


def test_us_grants_parse_mixed_separators_and_class_trailers():
    t = "6,324.298 B1 * 11/2001 O'Dell et al. ............... 382, 149 6,779,386 B2 * 8/2004 Neo et al."
    got = extract_cited_us_patents_from_refs(t, "")
    digits = [each["digits"] for each in got]
    assert "6324298" in digits
    assert "6779386" in digits
