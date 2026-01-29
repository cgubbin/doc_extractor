from patent_ingest.front_matter.assignee import extract_assignee
from patent_ingest.front_matter.inid import parse_inid_blocks_raw

from conftest import mp, diag_codes


def test_assignee_prefers_73_over_71(diag, linconf):
    doc = mp(
        ("(71) Applicant: AAA", "(73) Assignee: BBB (US)"),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_assignee(inids, diag)
    assert out is not None
    assert out.value.startswith("BBB")
    assert out.meta["inid_code"] == "73"


def test_assignee_cleaned_empty_warns(diag, linconf):
    doc = mp(
        ("(73) Assignee: (*) Notice: Subject to any disclaimer", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_assignee(inids, diag)
    assert out is not None
    assert out.value == ""
    assert "assignee.cleaned_empty" in diag_codes(diag)["warnings"]
