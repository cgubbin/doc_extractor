from __future__ import annotations

from typing import Dict, List
import pymupdf

from patent_ingest.model.model import Col, Line

_PUNCT_NO_SPACE_BEFORE = {",", ".", ";", ":", ")", "]", "}", "%"}
_PUNCT_NO_SPACE_AFTER = {"(", "[", "{"}


def _join_words_stably(words: list[tuple[float, float, float, float, str]]) -> str:
    if not words:
        return ""
    words = sorted(words, key=lambda w: w[0])
    out: list[str] = []
    prev = ""
    for x0, y0, x1, y1, t in words:
        t = t.strip()
        if not t:
            continue
        if not out:
            out.append(t)
        else:
            if (
                t in _PUNCT_NO_SPACE_BEFORE
                or prev in _PUNCT_NO_SPACE_AFTER
                or prev.endswith("-")
            ):
                out.append(t)
            else:
                out.append(" " + t)
        prev = t
    return "".join(out).strip()


def _split_words_by_largest_gap(
    ws: list[tuple[float, float, float, float, str]],
    *,
    min_gap: float = 22.0,
) -> tuple[
    list[tuple[float, float, float, float, str]],
    list[tuple[float, float, float, float, str]],
]:
    if len(ws) < 2:
        return ws, []
    ws = sorted(ws, key=lambda w: w[0])
    best_gap = 0.0
    best_i = -1
    for i in range(len(ws) - 1):
        gap = ws[i + 1][0] - ws[i][2]
        if gap > best_gap:
            best_gap = gap
            best_i = i
    if best_gap < min_gap:
        return ws, []
    return ws[: best_i + 1], ws[best_i + 1 :]


def extract_column_streams(
    page: pymupdf.Page,
    *,
    header_margin: float = 5.0,
    footer_margin: float = 5.0,
    min_split_gap: float = 22.0,
    mid_gutter: float = 10.0,
) -> Dict[Col, List[Line]]:
    """
    Extract word-level text, group into visual lines using (block_no, line_no),
    and assign each line to L/R. If a visual line contains both columns, split it.
    """
    rect = page.rect
    x_mid = rect.width / 2.0
    y_min = header_margin
    y_max = rect.height - footer_margin

    raw = page.get_text("words") or None
    # print(f"Extracted {len(raw) if raw else 0} words from page {page.number}")
    if not raw:
        # print("Retrying with OCR...")
        tp = page.get_textpage_ocr(
            language="eng", dpi=300, full=True
        )  # add "deu+eng" etc if needed
        raw = page.get_text("words", textpage=tp)
        # print(raw)
        # print(
        # f"Extracted {len(raw) if raw else 0} words from OCR on page {page.number}"
        # )

    line_map: dict[tuple[int, int], list[tuple[float, float, float, float, str]]] = {}

    # word tuple: x0,y0,x1,y1,text, block_no,line_no,word_no
    for w in raw:
        x0, y0, x1, y1, text, bno, lno, wno = w[:8]
        cy = 0.5 * (y0 + y1)
        if cy < y_min or cy > y_max:
            continue
        t = str(text).strip()
        if not t:
            continue
        line_map.setdefault((int(bno), int(lno)), []).append(
            (float(x0), float(y0), float(x1), float(y1), t)
        )

    L: List[Line] = []
    R: List[Line] = []

    for ws in line_map.values():
        minx = min(w[0] for w in ws)
        maxx = max(w[2] for w in ws)
        miny = min(w[1] for w in ws)
        maxy = max(w[3] for w in ws)
        cx = 0.5 * (minx + maxx)

        left_words, right_words = _split_words_by_largest_gap(ws, min_gap=min_split_gap)

        if right_words:
            lt = _join_words_stably(left_words)
            rt = _join_words_stably(right_words)
            if lt:
                L.append(
                    Line(
                        y0=min(w[1] for w in left_words),
                        y1=max(w[3] for w in left_words),
                        x0=min(w[0] for w in left_words),
                        x1=max(w[2] for w in left_words),
                        text=lt,
                    )
                )
            if rt:
                R.append(
                    Line(
                        y0=min(w[1] for w in right_words),
                        y1=max(w[3] for w in right_words),
                        x0=min(w[0] for w in right_words),
                        x1=max(w[2] for w in right_words),
                        text=rt,
                    )
                )
        else:
            t = _join_words_stably(left_words)
            if not t:
                continue
            if cx > x_mid + mid_gutter:
                R.append(Line(y0=miny, y1=maxy, x0=minx, x1=maxx, text=t))
            else:
                L.append(Line(y0=miny, y1=maxy, x0=minx, x1=maxx, text=t))

    L.sort(key=lambda ln: ln.y)
    R.sort(key=lambda ln: ln.y)
    return {"L": L, "R": R}
