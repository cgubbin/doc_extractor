from patent_ingest.parse_body import _extract_figure_ids


def test_extract_figure_ids_single_and_plural():
    text = "FIG. 1 shows something. FIGS. 2 and 3 show other things."
    ids_ = _extract_figure_ids(text)
    assert ids_ == ["1", "2", "3"]


def test_extract_figure_ids_letter_suffix_range():
    text = "FIGS. 2A-2C illustrate embodiments."
    ids_ = _extract_figure_ids(text)
    assert ids_ == ["2A", "2B", "2C"]


def test_extract_figure_ids_dedup_and_sort():
    text = "FIG. 3 shows. FIG. 1 shows. FIG. 3 shows again."
    ids_ = _extract_figure_ids(text)
    assert ids_ == ["1", "3"]
