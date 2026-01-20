from enum import Enum
from dataclasses import dataclass
from typing import List, Sequence, Tuple, Union


class Column(Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, order=True)
class Position:
    """A point in the extracted text stream."""

    page: int  # 0-based
    column: Column  # LEFT/RIGHT
    offset: int  # 0-based character offset within that column string


@dataclass(frozen=True)
class Span:
    """Half-open span [start, end). Must be within the same page+column unless you use MultiSpan."""

    start: Position
    end: Position

    def __post_init__(self) -> None:
        # Basic sanity checks
        if (self.start.page, self.start.column.value) != (
            self.end.page,
            self.end.column.value,
        ):
            raise ValueError(
                "Span must be within one page+column. Use MultiSpan for cross-boundary spans."
            )
        if self.end.offset < self.start.offset:
            raise ValueError("Span end must be >= start.")

    @property
    def page(self) -> int:
        return self.start.page

    @property
    def pages(self) -> List[int]:
        return [self.start.page]

    @property
    def column(self) -> Column:
        return self.start.column

    def __repr__(self) -> str:
        return f"Span(p{self.page}:{self.column.value}@{self.start.offset}..{self.end.offset})"


@dataclass(frozen=True)
class MultiSpan:
    """A collection of spans that together represent one logical selection."""

    parts: tuple[Span, ...]

    def __post_init__(self) -> None:
        if not self.parts:
            raise ValueError("MultiSpan must have at least one Span.")

    def __repr__(self) -> str:
        inner = ", ".join(repr(p) for p in self.parts)
        return f"MultiSpan({inner})"

    @property
    def pages(self) -> List[int]:
        all = [p.page for p in self.parts]
        return list(sorted(set(all)))  # unique, sorted


Where = Union[Span, MultiSpan]


def _span_sort_key(s: Span) -> Tuple[int, int, int, int]:
    # page, column-order, start, end
    col_ord = 0 if s.column is Column.LEFT else 1
    return (s.page, col_ord, s.start.offset, s.end.offset)


def merge_where(a: Where, b: Where) -> Where:
    """
    Merge two Where objects into a single Where.
    - If they can be coalesced (adjacent/overlapping within same page+column), do so.
    - Otherwise return a MultiSpan with ordered, coalesced parts.
    """
    parts: List[Span] = []
    parts.extend(a.parts if isinstance(a, MultiSpan) else (a,))
    parts.extend(b.parts if isinstance(b, MultiSpan) else (b,))
    parts.sort(key=_span_sort_key)
    parts = coalesce_spans(parts)
    return parts[0] if len(parts) == 1 else MultiSpan(parts=tuple(parts))


def coalesce_spans(spans: Sequence[Span]) -> List[Span]:
    """Coalesce overlapping/adjacent spans when they share the same page+column."""
    if not spans:
        return []
    out: List[Span] = []
    cur = spans[0]
    for s in spans[1:]:
        if (s.page, s.column) == (
            cur.page,
            cur.column,
        ) and s.start.offset <= cur.end.offset:
            # overlap/adjacent (adjacent if s.start == cur.end)
            new_end = Position(cur.page, cur.column, max(cur.end.offset, s.end.offset))
            cur = Span(cur.start, new_end)
        elif (s.page, s.column) == (
            cur.page,
            cur.column,
        ) and s.start.offset == cur.end.offset:
            new_end = Position(cur.page, cur.column, s.end.offset)
            cur = Span(cur.start, new_end)
        else:
            out.append(cur)
            cur = s
    out.append(cur)
    return out


# =========================
# Debug helpers
# =========================


def format_where(where: Where) -> str:
    if isinstance(where, Span):
        return f"p{where.page}:{where.column.value}@{where.start.offset}..{where.end.offset}"
    return " + ".join(
        f"p{s.page}:{s.column.value}@{s.start.offset}..{s.end.offset}"
        for s in where.parts
    )
