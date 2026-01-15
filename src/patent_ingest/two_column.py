import pymupdf
from dataclasses import dataclass


@dataclass(frozen=True)
class TwoColumnRead:
    left: str
    right: str

    def normalize(self, f) -> "TwoColumnRead":
        return TwoColumnRead(
            left=f(self.left),
            right=f(self.right),
        )


def extract_ordered_two_column_text(
    reader, page_index: int, *, header_margin: float = 25, footer_margin: float = 25
) -> TwoColumnRead:
    """
    Reconstruct text order for USPTO-style two-column pages:
      - group fragments into lines by y (within y_tol)
      - split each line into left/right by a robust x_split
      - emit left column top-to-bottom, then right column top-to-bottom
    """
    page = reader.load_page(page_index)

    (x0, y0, x1, y1) = page.mediabox

    left_col_mediabox = pymupdf.Rect(
        x0, y0 - header_margin, x0 + (x1 - x0) / 2, y1 + footer_margin
    )

    right_col_mediabox = pymupdf.Rect(
        x0 + (x1 - x0) / 2, y0 - header_margin, x1, y1 + footer_margin
    )

    left_text = page.get_textbox(left_col_mediabox)
    right_text = page.get_textbox(right_col_mediabox)

    return TwoColumnRead(left=left_text, right=right_text)
