from patent_ingest.model.span import Column
import pymupdf
from enum import Enum, auto

from patent_ingest.model.row import (
    extract_two_column_rows,
    split_body_header,
    column_stream,
    bind_inid_blocks_in_stream,
    merge_bound_streams_to_rows,
)


class Region(Enum):
    HEADER = auto()
    BODY = auto()
    ALL = auto()


class LinearizeMode(Enum):
    ROW_MAJOR = auto()  # y-sorted rows, left then right per row
    COLUMN_MAJOR = auto()  # full left column top-to-bottom, then full right


class TwoColumn:
    def __init__(self, doc, page_index: int, *, header_margin=20, footer_margin=20):
        page = doc.load_page(page_index)

        all_rows = extract_two_column_rows(
            page,
            header_margin=header_margin,
            footer_margin=footer_margin,
            min_split_gap=22.0,
            gutter=10.0,
        )

        # Your existing header/body split (anchor or whatever you have)
        self.header_rows, self.body_rows = split_body_header(
            all_rows, prelude_max_dy=10.0
        )  # <-- keep your working split

        L = column_stream(self.body_rows, "L")
        R = column_stream(self.body_rows, "R")

        L_bound = bind_inid_blocks_in_stream(L, prefix_window=80.0)
        R_bound = bind_inid_blocks_in_stream(R, prefix_window=80.0)

        body_rows_bound = merge_bound_streams_to_rows(L_bound, R_bound)
        self.body_rows = body_rows_bound

        # # Critical: fix INID ordering in BODY
        # self.body_rows = bind_inid_fields(
        #     self.body_rows,
        #     take_above=3,
        #     max_above_dy=120,
        #     prelude_buffer=30,
        #     max_field_span=400,
        # )
        for each in self.body_rows:
            print(each)
        raise RuntimeError("debug")

        # Canonical column strings (BODY ONLY) for Span offsets
        self._left_body = "\n".join(r.left for r in self.body_rows if r.left).strip()
        self._right_body = "\n".join(r.right for r in self.body_rows if r.right).strip()

        # Optional header strings
        self._left_header = "\n".join(
            r.left for r in self.header_rows if r.left
        ).strip()
        self._right_header = "\n".join(
            r.right for r in self.header_rows if r.right
        ).strip()

    @property
    def left(self) -> str:
        return self._left_body

    @property
    def right(self) -> str:
        return self._right_body

    @property
    def header_left(self) -> str:
        return self._left_header

    @property
    def header_right(self) -> str:
        return self._right_header

    def linearize(self, *, include_header: bool = True) -> str:
        """
        Column-major linearization:
          header left, header right, body left, body right
        This avoids cross-column interleaving.
        """
        parts = []
        if include_header:
            if self._left_header:
                parts.append(self._left_header)
            if self._right_header:
                parts.append(self._right_header)
        if self._left_body:
            parts.append(self._left_body)
        if self._right_body:
            parts.append(self._right_body)
        return "\n".join(parts)


class MultiPage:
    def __init__(self, doc, page_range: range, *, header_margin=20, footer_margin=20):
        self.pages = [
            TwoColumn(doc, i, header_margin=header_margin, footer_margin=footer_margin)
            for i in page_range
        ]

    def __len__(self) -> int:
        return len(self.pages)

    def get_column_text(
        self, page: int, column: Column, *, region: Region = Region.BODY
    ) -> str:
        match region:
            case Region.HEADER:
                if column is Column.LEFT:
                    return self.pages[page].header_left
                else:
                    return self.pages[page].header_right
            case Region.BODY:
                if column is Column.LEFT:
                    return self.pages[page]._left_body
                else:
                    return self.pages[page]._right_body
            case Region.ALL:
                if column is Column.LEFT:
                    return (
                        self.pages[page]._left_header
                        + "\n"
                        + self.pages[page]._left_body
                    )
                if column is Column.RIGHT:
                    return (
                        self.pages[page]._right_header
                        + "\n"
                        + self.pages[page]._right_body
                    )

    def linearize(self) -> str:
        return "\n".join(p.linearize(include_header=False) for p in self.pages)

    # ---- slicing ----

    def slice_span(self, span) -> str:
        """
        Requires span.start and span.end to agree on page/column/region.
        """
        start = span.start
        end = span.end

        if (start.page, start.column, getattr(start, "region", Region.BODY)) != (
            end.page,
            end.column,
            getattr(end, "region", Region.BODY),
        ):
            raise ValueError(
                "Span slicing only supported within one (page, column, region)"
            )

        region = getattr(start, "region", Region.BODY)
        txt = self.get_column_text(start.page, start.column, region=region)
        return txt[start.offset : end.offset]

    def slice_where(self, where, *, joiner: str = "") -> str:
        # same shape you already have: Where is either Span or composite with .parts
        if hasattr(where, "parts"):
            return joiner.join(self.slice_span(s) for s in where.parts)
        return self.slice_span(where)

    def subset(self, pages: range) -> "MultiPage":
        mp = MultiPage.__new__(MultiPage)
        mp.pages = [self.pages[i] for i in pages]
        return mp


#
# class TwoColumn:
#     left: str
#     right: str
#
#     def __init__(
#         self,
#         doc: Document,
#         page_index: int,
#         *,
#         header_margin: float = 25,
#         footer_margin: float = 25,
#     ) -> "TwoColumn":
#         page = doc.load_page(page_index)
#
#         (x0, y0, x1, y1) = page.mediabox
#
#     left_col_mediabox = pymupdf.Rect(
#         x0, y0 - header_margin, x0 + (x1 - x0) / 2, y1 + footer_margin
#     )
#
#     right_col_mediabox = pymupdf.Rect(
#         x0 + (x1 - x0) / 2, y0 - header_margin, x1, y1 + footer_margin
#     )
#
#     self.left = page.get_textbox(left_col_mediabox)
#     self.right = page.get_textbox(right_col_mediabox)
#
# def linearize(self) -> str:
#     return self.left + "\n" + self.right


# class MultiPage:
#     pages: list[TwoColumn]
#
#     def __init__(
#         self,
#         doc: Document,
#         page_range: range,
#         *,
#         header_margin: float = 25,
#         footer_margin: float = 25,
#     ) -> "MultiPage":
#         self.pages = []
#         for each in page_range:
#             self.pages.append(
#                 TwoColumn(
#                     doc, each, header_margin=header_margin, footer_margin=footer_margin
#                 )
#             )
#
#     def __len__(self) -> int:
#         return len(self.pages)
#
#     def get_column_text(self, page: int, column: Column) -> str:
#         p = self.pages[page]
#         return p.left if column is Column.LEFT else p.right
#
#     def slice_span(self, span: Span) -> str:
#         txt = self.get_column_text(span.start.page, span.start.column)
#         return txt[span.start.offset : span.end.offset]
#
#     def slice_where(self, where: Where, *, joiner: str = "") -> str:
#         if isinstance(where, Span):
#             return self.slice_span(where)
#         return joiner.join(self.slice_span(s) for s in where.parts)
#
#     def subset(self, pages: range) -> "MultiPage":
#         mp = MultiPage.__new__(MultiPage)
#         mp.pages = [self.pages[i] for i in pages]
#         return mp
#
#     def linearize(self) -> str:
#         return "\n".join(p.linearize() for p in self.pages)
#
#
def read_pdf_to_multipage(
    filepath: str,
    *,
    page_range: range | None = None,
    header_margin: float = 25,
    footer_margin: float = 25,
) -> MultiPage:
    with pymupdf.open(filepath) as doc:
        if page_range is None:
            page_range = range(len(doc))
        mp = MultiPage(
            doc,
            page_range,
            header_margin=header_margin,
            footer_margin=footer_margin,
        )
    return mp
