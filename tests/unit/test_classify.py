# tests/unit/test_classify.py
from __future__ import annotations

from patent_ingest.model.classify import classify_page
from tests.helpers import make_layout, L, R


def test_drawing_detected_by_sheet_header():
    lay = make_layout(
        header_L=[L(60, "Patent Application Publication")],
        header_R=[R(60, "Mar. 3, 2011 Sheet 4 of 10")],
        body_L=[L(300, "Fig. 4")],
        body_R=[],
    )
    pt = classify_page(lay)
    assert pt.kind == "drawing"
