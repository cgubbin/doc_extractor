from __future__ import annotations

from typing import Iterable

from patent_ingest.model.model import Line, ColumnStream, PageLayout


def norm(s: str) -> str:
    return " ".join((s or "").split())


def L(y: float, text: str, x0: float = 80.0, x1: float = 280.0) -> Line:
    return Line(y0=y - 2, y1=y + 2, x0=x0, x1=x1, text=text)


def R(y: float, text: str, x0: float = 320.0, x1: float = 520.0) -> Line:
    return Line(y0=y - 2, y1=y + 2, x0=x0, x1=x1, text=text)


def make_layout(
    *,
    page_index: int = 0,
    header_L: Iterable[Line] = (),
    header_R: Iterable[Line] = (),
    body_L: Iterable[Line] = (),
    body_R: Iterable[Line] = (),
) -> PageLayout:
    return PageLayout(
        page_index=page_index,
        header={
            "L": ColumnStream("L", tuple(header_L)),
            "R": ColumnStream("R", tuple(header_R)),
        },
        body={
            "L": ColumnStream("L", tuple(body_L)),
            "R": ColumnStream("R", tuple(body_R)),
        },
    )
