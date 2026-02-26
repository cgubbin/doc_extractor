from __future__ import annotations

import re
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


def _is_likely_line_number(text: str) -> bool:
    """
    Check if text is likely a line/paragraph number (short numeric token).

    IMPORTANT: Excludes:
    - Parenthesized numbers like "(10)", "(21)" - INID codes
    - Numbers with period like "6.", "17." - claim/list markers
    """
    text = text.strip()
    if len(text) > 6:
        return False

    # Never filter parenthesized numbers - these are INID codes
    if text.startswith('(') and text.endswith(')'):
        return False

    # Never filter numbers followed by period - these are claim/list markers
    if re.match(r'^\d{1,3}\.$', text):
        return False

    # Match pure numbers or numbers with minimal decoration
    return text.isdigit() or (len(text) <= 4 and any(c.isdigit() for c in text))


def _split_into_clusters(
    ws: list[tuple[float, float, float, float, str]],
    *,
    min_gap: float = 15.0,
) -> list[list[tuple[float, float, float, float, str]]]:
    """
    Split words into clusters separated by ALL gaps >= min_gap.

    This handles cases where centered line numbers sit between columns:
      "text" [gap 30] "17" [gap 28] "more text"
    Produces: [["text"], ["17"], ["more text"]]

    Returns list of word clusters, each cluster is a list of word tuples.
    """
    if not ws:
        return []

    ws = sorted(ws, key=lambda w: w[0])
    clusters = [[ws[0]]]

    for i in range(1, len(ws)):
        gap = ws[i][0] - ws[i - 1][2]
        if gap >= min_gap:
            # Significant gap - start new cluster
            clusters.append([ws[i]])
        else:
            # Same cluster
            clusters[-1].append(ws[i])

    return clusters


def _filter_centered_line_numbers(
    ws: list[tuple[float, float, float, float, str]],
    x_mid: float,
    page_width: float,
) -> list[tuple[float, float, float, float, str]]:
    """
    Remove short numeric tokens (line numbers) that appear near the page center.

    Detects patterns like: "thick- 30 upper" and removes the "30".
    """
    if len(ws) <= 1:
        return ws

    filtered = []
    center_zone = page_width * 0.15

    for w in ws:
        x0, y0, x1, y1, text = w
        cx = 0.5 * (x0 + x1)

        # If it's a likely line number AND positioned near center, skip it
        if _is_likely_line_number(text) and abs(cx - x_mid) < center_zone:
            continue

        filtered.append(w)

    return filtered


def extract_column_streams(
    page: pymupdf.Page,
    *,
    header_margin: float = 5.0,
    footer_margin: float = 5.0,
    min_split_gap: float = 22.0,
    mid_gutter: float = 10.0,
    filter_line_numbers: bool = True,
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

    # First pass: collect all lines and their widths to compute average
    line_data = []
    for ws in line_map.values():
        minx = min(w[0] for w in ws)
        maxx = max(w[2] for w in ws)
        width = maxx - minx
        line_data.append((ws, width))

    # Compute median line width (more robust than mean)
    if line_data:
        widths = sorted([w for _, w in line_data])
        median_width = widths[len(widths) // 2]
    else:
        median_width = 0

    # Second pass: process lines, filtering line numbers from abnormally long lines
    for ws, width in line_data:
        # If line is abnormally long (> 1.5x median), filter centered line numbers
        # BUT only if filter_line_numbers is enabled (disabled for INID/front pages)
        if filter_line_numbers and median_width > 0 and width > median_width * 1.5:
            ws_filtered = _filter_centered_line_numbers(ws, x_mid, rect.width)
        else:
            ws_filtered = ws

        if not ws_filtered:
            continue

        minx = min(w[0] for w in ws_filtered)
        maxx = max(w[2] for w in ws_filtered)
        miny = min(w[1] for w in ws_filtered)
        maxy = max(w[3] for w in ws_filtered)
        cx = 0.5 * (minx + maxx)

        left_words, right_words = _split_words_by_largest_gap(ws_filtered, min_gap=min_split_gap)

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
            # No clear split found - try clustering with lower threshold
            clusters = _split_into_clusters(ws_filtered, min_gap=15.0)

            if len(clusters) == 1:
                # Single cluster - assign to L or R based on position (original logic)
                t = _join_words_stably(left_words)
                if not t:
                    continue
                if cx > x_mid + mid_gutter:
                    R.append(Line(y0=miny, y1=maxy, x0=minx, x1=maxx, text=t))
                else:
                    L.append(Line(y0=miny, y1=maxy, x0=minx, x1=maxx, text=t))
            else:
                # Multiple clusters - classify each as L/R based on position
                for cluster in clusters:
                    minx_c = min(w[0] for w in cluster)
                    maxx_c = max(w[2] for w in cluster)
                    miny_c = min(w[1] for w in cluster)
                    maxy_c = max(w[3] for w in cluster)
                    cx_c = 0.5 * (minx_c + maxx_c)
                    t = _join_words_stably(cluster)
                    if not t:
                        continue

                    # Assign to L or R based on position relative to page midpoint
                    if cx_c > x_mid:
                        R.append(Line(y0=miny_c, y1=maxy_c, x0=minx_c, x1=maxx_c, text=t))
                    else:
                        L.append(Line(y0=miny_c, y1=maxy_c, x0=minx_c, x1=maxx_c, text=t))

    L.sort(key=lambda ln: ln.y)
    R.sort(key=lambda ln: ln.y)
    return {"L": L, "R": R}
