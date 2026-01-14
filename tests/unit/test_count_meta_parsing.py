from patent_ingest.parse_front_page import extract_reported_counts


def test_reported_counts_claims_and_sheets():
    t = "(57) ABSTRACT ... 16 claims, 4 drawing sheets"
    got = extract_reported_counts(t)
    assert got["reported_claim_count"] == 16
    assert got["reported_drawing_sheet_count"] == 4
