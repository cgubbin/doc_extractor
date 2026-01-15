from patent_ingest.model.span import Span, Where, Column
from pymupdf import Document
import pymupdf


class TwoColumn:
    left: str
    right: str

    def __init__(
        self,
        doc: Document,
        page_index: int,
        *,
        header_margin: float = 25,
        footer_margin: float = 25,
    ) -> "TwoColumn":
        page = doc.load_page(page_index)

        (x0, y0, x1, y1) = page.mediabox

        left_col_mediabox = pymupdf.Rect(
            x0, y0 - header_margin, x0 + (x1 - x0) / 2, y1 + footer_margin
        )

        right_col_mediabox = pymupdf.Rect(
            x0 + (x1 - x0) / 2, y0 - header_margin, x1, y1 + footer_margin
        )

        self.left = page.get_textbox(left_col_mediabox)
        self.right = page.get_textbox(right_col_mediabox)


class MultiPage:
    pages: list[TwoColumn]

    def __init__(
        self,
        doc: Document,
        page_range: range,
        *,
        header_margin: float = 25,
        footer_margin: float = 25,
    ) -> "MultiPage":
        self.pages = []
        for each in page_range:
            self.pages.append(
                TwoColumn(
                    doc, each, header_margin=header_margin, footer_margin=footer_margin
                )
            )

    def __len__(self) -> int:
        return len(self.pages)

    def get_column_text(self, page: int, column: Column) -> str:
        p = self.pages[page]
        return p.left if column is Column.LEFT else p.right

    def slice_span(self, span: Span) -> str:
        txt = self.get_column_text(span.start.page, span.start.column)
        return txt[span.start.offset : span.end.offset]

    def slice_where(self, where: Where, *, joiner: str = "") -> str:
        if isinstance(where, Span):
            return self.slice_span(where)
        return joiner.join(self.slice_span(s) for s in where.parts)
