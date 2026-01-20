from patent_ingest.front_matter.application_number import extract_application_number
from patent_ingest.front_matter.inid import parse_inid_blocks_raw

from conftest import mp


def test_application_number_normalizes_prefix_leading_zero(diag, linconf):
    doc = mp(
        ("(21) Appl. No.: 016/197,849", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_application_number(doc, inids, diag)
    assert out is not None
    # Depending on your return: out.value or out.meta["normalized"]
    assert out.value.startswith("16/")  # NOT "016/"
