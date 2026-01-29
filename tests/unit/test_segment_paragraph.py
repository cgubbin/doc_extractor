from __future__ import annotations
import re
from typing import List

from patent_ingest.model.model import ColumnStream, Line
from patent_ingest.model.segment_para import segment_paragraph_blocks
from tests.helpers import L

from hypothesis import given, settings, strategies as st


def test_section_heading_emitted_and_splits():
    from patent_ingest.model.model import ColumnStream

    cs = ColumnStream(
        "L",
        tuple(
            [
                L(100, "BACKGROUND"),
                L(120, "This disclosure relates to semiconductor processing."),
                L(140, "More particularly, it relates to wafer monitoring."),
            ]
        ),
    )

    blocks = segment_paragraph_blocks(cs, region="body", emit_heading_blocks=True)
    kinds = [b.kind for b in blocks]
    assert "section_heading" in kinds
    assert any(b.kind == "paragraph" for b in blocks)

    # heading should be first here
    assert blocks[0].kind == "section_heading"
    assert blocks[0].text.strip().upper() == "BACKGROUND"


def test_digits_only_not_heading():
    from patent_ingest.model.model import ColumnStream

    cs = ColumnStream(
        "L",
        tuple(
            [
                L(100, "BACKGROUND"),
                L(120, "0017"),
                L(140, "This is not a section heading; it's a label/marker."),
            ]
        ),
    )

    blocks = segment_paragraph_blocks(cs, region="body", emit_heading_blocks=True)

    # No heading/subheading blocks should have digits-only text
    for b in blocks:
        if b.kind in ("section_heading", "subheading"):
            assert not b.text.strip().isdigit()


def test_subheading_emitted_but_not_digits():
    from patent_ingest.model.model import ColumnStream

    cs = ColumnStream(
        "L",
        tuple(
            [
                L(100, "DETAILED DESCRIPTION"),
                L(115, "OVERVIEW"),
                L(130, "The system includes..."),
                L(150, "0019"),
                L(165, "More details follow."),
            ]
        ),
    )

    blocks = segment_paragraph_blocks(
        cs, region="body", emit_heading_blocks=True, subheadings_are_boundaries=True
    )

    # Should contain section heading and subheading, but "0019" must not be a heading
    assert any(b.kind == "section_heading" for b in blocks)
    assert any(b.kind == "subheading" for b in blocks)
    assert not any(
        (b.kind in ("section_heading", "subheading") and b.text.strip() == "0019")
        for b in blocks
    )


DIGITS_ONLY_RE = re.compile(r"^\s*\d+\s*$")


def mk_line(y: float, text: str, x0: float, x1: float) -> Line:
    return Line(y0=y - 2, y1=y + 2, x0=x0, x1=x1, text=text)


# --- Strategies ---


@st.composite
def line_texts(draw):
    """
    Generate a mix of:
      - section headings (known)
      - subheading-like caps lines
      - digits-only labels (the problematic case)
      - normal prose
    """
    kind = draw(st.sampled_from(["section", "subheading", "digits", "prose", "enum"]))
    if kind == "section":
        # Keep these aligned with KNOWN_SECTION_HEADINGS
        return draw(
            st.sampled_from(
                [
                    "BACKGROUND",
                    "SUMMARY",
                    "DETAILED DESCRIPTION",
                    "FIELD",
                    "TECHNICAL FIELD",
                    "BRIEF DESCRIPTION OF THE DRAWINGS",
                    "CLAIMS",
                    "ABSTRACT",
                ]
            )
        )
    if kind == "subheading":
        # Caps-ish but not a known section heading
        return draw(
            st.sampled_from(
                [
                    "OVERVIEW",
                    "EXAMPLES",
                    "IMPLEMENTATION",
                    "SYSTEM ARCHITECTURE",
                    "ALTERNATIVE EMBODIMENTS",
                ]
            )
        )
    if kind == "digits":
        # include 00xx patterns
        return draw(st.sampled_from(["0017", "0019", "0001", "12", "7", "1234"]))
    if kind == "enum":
        return draw(st.sampled_from(["(1)", "(2)", "I.", "A.", "1.", "2)"]))
    # prose
    return draw(
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs",)),
            min_size=20,
            max_size=80,
        ).map(lambda s: " ".join(s.split()) or "This is some patent prose text.")
    )


@st.composite
def column_streams(draw):
    """
    Generate a plausible single-column stream:
    - increasing y
    - x0 mostly near a margin with occasional indent
    """
    n = draw(st.integers(min_value=8, max_value=40))
    # start y in typical body range
    y0 = draw(st.floats(min_value=80, max_value=200))
    # typical line spacing
    dy_base = draw(st.floats(min_value=8, max_value=14))

    # margin/width model
    margin = draw(st.floats(min_value=60, max_value=110))
    width = draw(st.floats(min_value=180, max_value=260))

    ys: List[float] = []
    y = y0
    for _ in range(n):
        # jittered spacing, sometimes big gap
        gap = draw(
            st.one_of(
                st.floats(min_value=dy_base * 0.7, max_value=dy_base * 1.5),
                st.floats(min_value=dy_base * 2.5, max_value=dy_base * 4.5),
            )
        )
        y += gap
        ys.append(y)

    lines: List[Line] = []
    for y in ys:
        txt = draw(line_texts())

        # occasional indent
        indent = draw(st.one_of(st.just(0.0), st.floats(min_value=8, max_value=22)))
        x0 = margin + indent
        x1 = x0 + width

        lines.append(mk_line(y, txt, x0=x0, x1=x1))

    return ColumnStream("L", tuple(lines))


# --- Properties ---


@given(cs=column_streams())
@settings(max_examples=250, deadline=None)
def test_no_digits_only_emitted_as_heading_kinds(cs: ColumnStream):
    blocks = segment_paragraph_blocks(
        cs, region="body", emit_heading_blocks=True, subheadings_are_boundaries=True
    )

    for b in blocks:
        if b.kind in ("section_heading", "subheading"):
            assert not DIGITS_ONLY_RE.match(b.text.strip()), (
                f"digits-only heading leaked: {b.text!r}"
            )


@given(cs=column_streams())
@settings(max_examples=250, deadline=None)
def test_blocks_are_monotone_in_y(cs: ColumnStream):
    blocks = segment_paragraph_blocks(
        cs, region="body", emit_heading_blocks=True, subheadings_are_boundaries=True
    )
    y0s = [b.y0 for b in blocks]
    assert y0s == sorted(y0s)


@given(cs=column_streams())
@settings(max_examples=250, deadline=None)
def test_section_headings_are_standalone(cs: ColumnStream):
    blocks = segment_paragraph_blocks(
        cs, region="body", emit_heading_blocks=True, subheadings_are_boundaries=True
    )

    for b in blocks:
        if b.kind == "section_heading":
            # should be a single logical line
            assert "\n" not in b.text.strip()
            assert len(b.text.strip()) <= 120
