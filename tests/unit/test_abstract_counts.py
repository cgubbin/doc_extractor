from patent_ingest.front_matter.abstract import extract_abstract
from patent_ingest.front_matter.counts import extract_reported_counts

from conftest import mp


def test_reported_counts_parse(diag, linconf):
    doc = mp(
        ("(57) ABSTRACT\nHello.\n12 Claims, 3 Drawing Sheets", ""),
    )
    out = extract_reported_counts(doc, diag, **linconf)
    assert out is not None
    assert out.value.reported_claim_count == 12
    assert out.value.reported_drawing_sheet_count == 3


def test_abstract_stops_at_counts(diag, linconf):
    doc = mp(
        ("(57) ABSTRACT\nA widget.\n12 Claims, 3 Drawing Sheets\nmore", ""),
    )
    out = extract_abstract(doc, diag, **linconf)
    assert out is not None
    assert "12 Claims" not in out.value
