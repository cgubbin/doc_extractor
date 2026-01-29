from patent_ingest.front_matter.patent_id import extract_patent_id
from patent_ingest.front_matter.inid import parse_inid_blocks_raw
from patent_ingest.parsed import EntityKind

from conftest import mp, diag_codes


def test_patent_id_from_inid_valid(diag, linconf):
    doc = mp(
        ("(10) Patent No.: US 7,629,993 B2", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    print("Found inids: ", inids)
    pid = extract_patent_id(doc, inids, diag, **linconf)
    assert pid is not None
    assert pid.kind == EntityKind.PATENT_ID
    assert pid.meta["validated"] is True
    assert "warnings" in diag_codes(diag)


def test_patent_id_missing_emits_error(diag, linconf):
    doc = mp(("no id here", "still no id"))
    inids = parse_inid_blocks_raw(doc, **linconf)
    pid = extract_patent_id(doc, inids, diag, **linconf)
    assert pid is None
    assert "patent_id.missing" in diag_codes(diag)["errors"]
