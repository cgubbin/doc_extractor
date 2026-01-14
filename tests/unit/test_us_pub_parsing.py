from patent_ingest.parse_front_page import extract_us_publications_from_refs


def test_us_pubs_parse_runin_kindcode_date():
    t = "2009 / 0087756 A14 / 2009 Schulz 2013/0271595 A1* 10/2013 Foo"
    got = extract_us_publications_from_refs(t)
    canons = [x["canonical"] for x in got]
    assert "20090087756" in canons
    assert "20130271595" in canons


def test_us_pubs_parse_O_instead_of_0_and_dots():
    t = "2008/O1653.57 A1 7/2008 Stern et al."
    got = extract_us_publications_from_refs(t)
    canons = [x["canonical"] for x in got]
    assert "20080165357" in canons


def test_foreign_wo_does_not_pollute_us_publications():
    t = "WO 2019/147828 A1 7/2019 Example et al. 2019/0123456 A1 5/2019 Smith"
    got = extract_us_publications_from_refs(t)
    canons = [x["canonical"] for x in got]
    assert "20190123456" in canons
    assert "2019147828" not in canons
