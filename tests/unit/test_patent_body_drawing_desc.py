import pytest

from patent_ingest.parse_body import (
    _parse_fig_id,
    _expand_fig_range,
    _parse_figlist,
    extract_drawing_descriptions,
)


def test_parse_fig_id_number_only():
    assert _parse_fig_id("3") == (3, None)
    assert _parse_fig_id("  10 ") == (10, None)


def test_parse_fig_id_number_with_suffix():
    assert _parse_fig_id("3A") == (3, "A")
    assert _parse_fig_id("3a") == (3, "A")
    assert _parse_fig_id("  12 b  ") == (12, "B")


def test_parse_fig_id_invalid_raises():
    with pytest.raises(ValueError):
        _parse_fig_id("A3")
    with pytest.raises(ValueError):
        _parse_fig_id("FIG. 3")
    with pytest.raises(ValueError):
        _parse_fig_id("")


def test_expand_fig_range_numeric():
    assert _expand_fig_range("2", "5") == ["2", "3", "4", "5"]
    assert _expand_fig_range("5", "5") == ["5"]


def test_expand_fig_range_letter_suffix_same_number():
    assert _expand_fig_range("2A", "2C") == ["2A", "2B", "2C"]
    assert _expand_fig_range("2b", "2d") == ["2B", "2C", "2D"]


def test_expand_fig_range_mismatch_falls_back():
    # different base numbers should not expand; best-effort return endpoints
    assert _expand_fig_range("2A", "3C") == ["2A", "3C"]
    # letter range reversed should not expand
    assert _expand_fig_range("2C", "2A") == ["2C", "2A"]


def test_parse_figlist_single():
    assert _parse_figlist("3") == ["3"]
    assert _parse_figlist("3A") == ["3A"]


def test_parse_figlist_letter_range():
    assert _parse_figlist("1A-1C") == ["1A", "1B", "1C"]


def test_parse_figlist_numeric_range():
    assert _parse_figlist("3-5") == ["3", "4", "5"]


def test_parse_figlist_commas_and_and():
    assert _parse_figlist("2, 3 and 4") == ["2", "3", "4"]
    assert _parse_figlist("2 and 3") == ["2", "3"]


def test_parse_figlist_mixed_range_and_list():
    # Mixed list: range + single + single
    assert _parse_figlist("1A-1C, 2 and 3") == ["1A", "1B", "1C", "2", "3"]


def test_parse_figlist_deduplicates_preserving_order():
    assert _parse_figlist("2, 2, 2A, 2A and 2") == ["2", "2A"]


def test_extract_drawing_descriptions_single_fig():
    text = "FIG. 1 is a side view of the apparatus."
    rows = extract_drawing_descriptions(text)
    assert rows == [
        {
            "figure_number": 1,
            "figure_suffix": None,
            "description": "is a side view of the apparatus.",
            "raw_reference": "FIG. 1",
        }
    ]


def test_extract_drawing_descriptions_figs_letter_range():
    text = "FIGS. 2A-2C illustrate alternative embodiments."
    rows = extract_drawing_descriptions(text)

    keys = [(r["figure_number"], r["figure_suffix"]) for r in rows]
    assert keys == [(2, "A"), (2, "B"), (2, "C")]
    for r in rows:
        assert r["description"] == "illustrate alternative embodiments."
        assert r["raw_reference"].startswith("FIGS.")


def test_extract_drawing_descriptions_figs_numeric_range():
    text = "FIGS. 3-5 show steps of the process."
    rows = extract_drawing_descriptions(text)

    keys = [(r["figure_number"], r["figure_suffix"]) for r in rows]
    assert keys == [(3, None), (4, None), (5, None)]
    for r in rows:
        assert r["description"] == "show steps of the process."


def test_extract_drawing_descriptions_multiple_entries_split_by_next_fig():
    text = "FIG. 1 is a first view. FIG. 2 is a second view."
    rows = extract_drawing_descriptions(text)
    assert len(rows) == 2

    assert rows[0]["figure_number"] == 1
    assert rows[0]["figure_suffix"] is None
    assert rows[0]["description"] == "is a first view."

    assert rows[1]["figure_number"] == 2
    assert rows[1]["figure_suffix"] is None
    assert rows[1]["description"] == "is a second view."


def test_extract_drawing_descriptions_commas_and_and_list():
    text = "FIGS. 2, 3 and 4 are perspective views of the device."
    rows = extract_drawing_descriptions(text)

    keys = [(r["figure_number"], r["figure_suffix"]) for r in rows]
    assert keys == [(2, None), (3, None), (4, None)]
    for r in rows:
        assert r["description"] == "are perspective views of the device."


def test_extract_drawing_descriptions_mixed_range_and_list():
    text = "FIGS. 1A-1C, 2 and 3 depict different configurations."
    rows = extract_drawing_descriptions(text)

    keys = [(r["figure_number"], r["figure_suffix"]) for r in rows]
    assert keys == [(1, "A"), (1, "B"), (1, "C"), (2, None), (3, None)]
    for r in rows:
        assert r["description"] == "depict different configurations."


def test_extract_drawing_descriptions_multiline_tolerance():
    text = "BRIEF DESCRIPTION OF THE DRAWINGS\nFIG. 1\nis a block diagram.\nFIG. 2 is a flowchart."
    rows = extract_drawing_descriptions(text)
    assert len(rows) == 2
    assert rows[0]["figure_number"] == 1
    assert rows[0]["description"] == "is a block diagram."
    assert rows[1]["figure_number"] == 2
    assert rows[1]["description"] == "is a flowchart."


def test_extract_drawing_descriptions_no_matches_returns_empty():
    text = "No figure descriptions here."
    assert extract_drawing_descriptions(text) == []


def test_extract_drawing_descriptions_ignores_invalid_ids_gracefully():
    # "FIG. X" should not create rows; valid ones should.
    text = "FIG. X is not valid. FIG. 1 is valid."
    rows = extract_drawing_descriptions(text)
    assert len(rows) == 1
    assert rows[0]["figure_number"] == 1
    assert rows[0]["figure_suffix"] is None
