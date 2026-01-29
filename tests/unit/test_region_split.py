# tests/unit/test_region_split.py
from __future__ import annotations

from patent_ingest.model.region import split_header_body_generic
from tests.helpers import L, R


def test_header_body_split_top_band():
    # header band around y ~ 60
    Ls = [L(60, "Patent Application Publication"), L(60, "US 2011/....")]
    Rs = [R(60, "Mar. 3, 2011 Sheet 1 of 10")]

    # body begins at y ~ 120
    Ls += [
        L(120, "WAFER FABRICATION MONITORING"),
        L(140, "EDGE BEAD REMOVAL PROCESSING"),
    ]
    Rs += [R(120, "Some right column body text")]

    header, body = split_header_body_generic(Ls, Rs, page_height=800)

    assert header["L"] and header["R"]
    assert body["L"] and body["R"]

    assert all(ln.y < 100 for ln in header["L"] + header["R"])
    assert all(ln.y > 90 for ln in body["L"] + body["R"])
