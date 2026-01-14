from patent_ingest.parse_front_page import extract_references_region


def test_refs_region_page0_sliced_to_abstract():
    pages_text = [
        "(56) References Cited U.S. PATENT DOCUMENTS 4,527,070 A ... (57) ABSTRACT some abstract text"
    ]
    got = extract_references_region(pages_text, max_pages=1)
    assert "ABSTRACT" not in got["raw"]
    assert "References Cited" in got["raw"]


def test_refs_region_continuation_page_strips_related_app_data_but_keeps_refs():
    pages_text = [
        "(56) References Cited U.S. PATENT DOCUMENTS 6,806,105 B2 (57) ABSTRACT ...",
        "Related U.S. Application Data ... now Pat. No. 8,649,016 ... (56) References Cited U.S. PATENT DOCUMENTS 6,878,301 B2 4/2005 Mundt",
    ]
    got = extract_references_region(pages_text, max_pages=2)
    assert "8,649,016" not in got["raw"]
    assert "6,878,301" in got["raw"]
