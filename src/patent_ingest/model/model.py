from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Iterator, List, Literal, Optional, Tuple


Col = Literal["L", "R"]
Region = Literal["header", "body"]


@dataclass(frozen=True)
class Line:
    # geometry in page coordinates
    y0: float
    y1: float
    x0: Optional[float] = None
    x1: Optional[float] = None
    text: str = ""

    @property
    def y(self) -> float:
        return 0.5 * (self.y0 + self.y1)


@dataclass(frozen=True)
class ColumnStream:
    col: Col
    lines: Tuple[Line, ...] = ()

    def __iter__(self) -> Iterator[Line]:
        return iter(self.lines)

    def texts(self) -> List[str]:
        return [ln.text for ln in self.lines if ln.text]

    def join(self) -> str:
        return "\n".join(self.texts()).strip()


@dataclass(frozen=True)
class PageLayout:
    page_index: int
    header: Dict[Col, ColumnStream]
    body: Dict[Col, ColumnStream]

    def stream(self, region: Region, col: Col) -> ColumnStream:
        return (self.header if region == "header" else self.body)[col]

    def linearize(
        self,
        *,
        include_header: bool = True,
        include_body: bool = True,
        mode: Literal["column-major", "row-major"] = "column-major",
    ) -> str:
        if mode == "column-major":
            parts: List[str] = []
            if include_header:
                for c in ("L", "R"):
                    t = self.header[c].join()
                    if t:
                        parts.append(t)
            if include_body:
                for c in ("L", "R"):
                    t = self.body[c].join()
                    if t:
                        parts.append(t)
            return "\n".join(parts).strip()

        # row-major is mainly a debug view
        lines: List[Tuple[float, str]] = []
        if include_header:
            for c in ("L", "R"):
                for ln in self.header[c]:
                    lines.append((ln.y, ln.text))
        if include_body:
            for c in ("L", "R"):
                for ln in self.body[c]:
                    lines.append((ln.y, ln.text))
        lines.sort(key=lambda t: t[0])
        return "\n".join(t for _, t in lines if t).strip()

    def split_cross_gutter_header_lines(self) -> "PageLayout":
        from doc_extractor.model.util import split_cross_gutter_header_lines

        l, r = split_cross_gutter_header_lines(
            self.header["L"].lines, self.header["R"].lines
        )

        return PageLayout(
            page_index=self.page_index,
            header={
                "L": ColumnStream(col="L", lines=l),
                "R": ColumnStream(col="R", lines=r),
            },
            body=self.body,
        )


@dataclass(frozen=True)
class Block:
    col: Col
    region: Region
    y0: float
    y1: float
    kind: Literal["inid", "paragraph", "unlabelled", "noise"]
    tag: Optional[int]
    text: str
