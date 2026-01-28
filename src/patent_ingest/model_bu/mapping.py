from dataclasses import dataclass
from typing import List, Tuple

from patent_ingest.model.document import Column, MultiPage
from patent_ingest.model.span import (
    MultiSpan,
    Position,
    Span,
    Where,
    _span_sort_key,
    coalesce_spans,
)


# =========================
# Linearization & mapping
# =========================


@dataclass(frozen=True)
class Segment:
    page: int
    column: Column
    text: str
    global_start: int  # inclusive
    global_end: int  # exclusive


def iter_segments(
    doc: MultiPage,
    order: Tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> List[Tuple[int, Column, str]]:
    out: List[Tuple[int, Column, str]] = []
    for pageno, page in enumerate(doc.pages):
        for col in order:
            txt = page.left if col is Column.LEFT else page.right
            out.append((pageno, col, txt))
    return out


def linearize(
    doc: MultiPage,
    *,
    sep: str = "\n",
    order: Tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Tuple[str, List[Segment]]:
    """
    Concatenate all page/column strings into a single string for regex scanning,
    while preserving enough metadata to map global offsets back to (page, column, offset).

    NOTE: sep is inserted between segments and is NOT part of any segment.
    """
    seg_meta: List[Segment] = []
    chunks: List[str] = []
    cursor = 0

    for page, col, txt in iter_segments(doc, order=order):
        chunks.append(txt)
        seg_meta.append(
            Segment(
                page=page,
                column=col,
                text=txt,
                global_start=cursor,
                global_end=cursor + len(txt),
            )
        )
        cursor += len(txt)

        # boundary separator (not attributable to any segment)
        chunks.append(sep)
        cursor += len(sep)

    return "".join(chunks), seg_meta


def global_range_to_where(
    global_start: int, global_end: int, segments: List[Segment]
) -> Where:
    """
    Map [global_start, global_end) into Span(s).
    Parts that fall into separators are ignored (clipped away).
    """
    if global_end <= global_start:
        raise ValueError("Empty/negative range")

    parts: List[Span] = []

    for seg in segments:
        a = max(global_start, seg.global_start)
        b = min(global_end, seg.global_end)
        if b <= a:
            continue
        start_pos = Position(seg.page, seg.column, a - seg.global_start)
        end_pos = Position(seg.page, seg.column, b - seg.global_start)
        parts.append(Span(start=start_pos, end=end_pos))

    if not parts:
        raise ValueError(
            "Range does not overlap any segment text (maybe entirely separators)."
        )

    parts.sort(key=_span_sort_key)
    parts = coalesce_spans(parts)
    return parts[0] if len(parts) == 1 else MultiSpan(parts=tuple(parts))


def trim_global_range(text: str, start: int, end: int) -> Tuple[int, int]:
    """
    Trim whitespace in a global slice [start,end) so that text[s:e] has no leading/trailing whitespace.
    """
    s, e = start, end
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e
