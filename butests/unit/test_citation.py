from patent_ingest.front_matter.citations import extract_citations

from conftest import mp


def test_citations_across_pages(diag, linconf):
    doc = mp(
        # page 0 has start + 2 citations
        ("(56) References Cited\nU.S. PATENT DOCUMENTS\n5,864,394\n6,123,456", ""),
        # page 1 continues with 16 citations (simulate a few)
        ("(Continued)\nU.S. PATENT DOCUMENTS\n7,000,001\n7,000,002\n7,000,003", ""),
    )
    out = extract_citations(doc, diag, **linconf)
    grants = [c.value for c in out if c.value.type == "US_GRANT"]
    assert len(grants) >= 5


def test_citations_excludes_foreign_pubapps(diag, linconf):
    doc = mp(
        (
            "(56) References Cited\nOTHER PUBLICATIONS\nWO 2019/147828 A1\nUS 2001/0043333 A1",
            "",
        ),
    )
    out = extract_citations(doc, diag, **linconf)
    canonicals = [c.value.canonical for c in out if c.value.type == "US_PUBAPP"]
    assert "20010043333" in canonicals
    assert "20190147828" not in canonicals  # should be excluded as foreign context


def test_citations_excludes_narrative_continuation(diag, linconf):
    doc = mp(
        (
            "continuation of application No. 13/134,716, filed on Jun. 15, 2011, now Pat. No. 8,649,016\n"
            "(56) References Cited\n"
            "U.S. PATENT DOCUMENTS\n5,864,394",
            "",
        ),
    )
    out = extract_citations(doc, diag, **linconf)
    grants = [c.value.canonical for c in out if c.value.type == "US_GRANT"]
    assert "8649016" not in grants  # narrative “now Pat. No.” should not be captured
    assert "5864394" in grants
