# tests/unit/test_stitch.py
from __future__ import annotations

from patent_ingest.model.model import Block

from patent_ingest.model.stitch import stitch_inid_blocks_across_pages


def test_stitch_only_leading_noninid_attaches():
    # page0 ends with INID (57)
    p0 = [
        Block(
            col="R",
            region="body",
            y0=100,
            y1=200,
            kind="inid",
            tag=57,
            text="(57)\nABSTRACT\nFirst part",
        ),
    ]
    # page1 starts with continuation near top
    p1 = [
        Block(
            col="R",
            region="body",
            y0=50,
            y1=80,
            kind="unlabelled",
            tag=None,
            text="Continuation line 1",
        ),
        Block(
            col="R",
            region="body",
            y0=90,
            y1=120,
            kind="paragraph",
            tag=None,
            text="Continuation line 2",
        ),
        Block(
            col="R",
            region="body",
            y0=300,
            y1=340,
            kind="inid",
            tag=60,
            text="(60)\nSomething else",
        ),
    ]

    out = stitch_inid_blocks_across_pages([p0, p1], top_y_max=220.0)

    assert "Continuation line 1" in out[0][0].text
    assert "Continuation line 2" in out[0][0].text

    # leading blocks removed from page1
    assert all("Continuation" not in b.text for b in out[1])
