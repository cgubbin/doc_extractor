from patent_ingest.parse_front_page import extract_assignee_clean


def test_assignee_strip_notice_and_subject_to_any_disclaimer():
    raw = (
        "Nanometrics Incorporated , Milpitas , CA ( US ) "
        "Notice : OTHER PUBLICATIONS Subject to any disclaimer , the term of this patent is extended ..."
    )
    inid_blocks = {"73": {"text": raw, "span": {"start": 0, "end": len(raw)}}}
    got = extract_assignee_clean(inid_blocks)
    assert got["value"] == "Nanometrics Incorporated, Milpitas, CA"


def test_assignee_stop_at_foreign_patent_documents_heading():
    raw = "Onto Innovation Inc., Wilmington, MA (US) FOREIGN PATENT DOCUMENTS ("
    inid_blocks = {"73": {"text": raw, "span": {"start": 0, "end": len(raw)}}}
    got = extract_assignee_clean(inid_blocks)
    assert got["value"] == "Onto Innovation Inc., Wilmington, MA"


def test_assignee_stop_at_foreign_prefix_refs():
    raw = "Onto Innovation Inc. , Wilmington , MA ( US ) EP KR 2650661 A1 10/2013 10-2009-0051031 5/2009 ( Continued )"
    inid_blocks = {"73": {"text": raw, "span": {"start": 0, "end": len(raw)}}}
    got = extract_assignee_clean(inid_blocks)
    assert got["value"] == "Onto Innovation Inc., Wilmington, MA"
