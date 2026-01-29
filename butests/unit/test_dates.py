from patent_ingest.front_matter.grant_date import extract_filed_date, extract_grant_date
from patent_ingest.front_matter.inid import parse_inid_blocks_raw

from conftest import mp


def test_filed_date_from_inid(diag, linconf):
    doc = mp(
        ("(22) Filed: Sep. 30, 2002", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_filed_date(doc, inids, diag, **linconf)
    assert out is not None
    assert out.meta["iso"] == "2002-09-30"


def test_grant_date_fallback_generic_first_date(diag, linconf):
    doc = mp(
        ("Some header\nDec. 8, 2009\nMore text", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_grant_date(doc, inids, diag, **linconf)
    assert out is not None
    assert out.meta["iso"] == "2009-12-08"
