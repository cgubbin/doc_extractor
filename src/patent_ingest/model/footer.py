from __future__ import annotations
from typing import List, Tuple, Optional
import pymupdf

import re
from doc_extractor.model.model import Line


def _rect_intersection_area(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    inter = a & b
    if inter.is_empty:
        return 0.0
    return max(0.0, inter.width) * max(0.0, inter.height)


def find_image_rects(page: pymupdf.Page) -> List[pymupdf.Rect]:
    d = page.get_text("dict")
    rects: List[pymupdf.Rect] = []
    for block in d.get("blocks", []):
        if block.get("type") == 1:
            x0, y0, x1, y1 = block.get("bbox", (0, 0, 0, 0))
            r = pymupdf.Rect(x0, y0, x1, y1)
            if not r.is_empty:
                rects.append(r)
    return rects


def _rect_area(r: pymupdf.Rect) -> float:
    return max(0.0, r.width) * max(0.0, r.height)


def remove_lines_overlapping_images(
    page: pymupdf.Page,
    lines: List[Line],
    image_rects: List[pymupdf.Rect],
    *,
    # reject huge “background” images (common in scanned docs)
    ignore_if_frac_page_area_ge: float = 0.45,
    # require meaningful overlap both vertically and horizontally
    min_v_overlap_frac: float = 0.60,
    min_h_overlap_frac: float = 0.25,
) -> List[Line]:
    if not lines or not image_rects:
        return lines

    page_area = _rect_area(page.rect)
    safe_rects: List[pymupdf.Rect] = []
    for ir in image_rects:
        if (
            page_area > 0
            and (_rect_area(ir) / page_area) >= ignore_if_frac_page_area_ge
        ):
            # treat as background raster; ignore it
            continue
        safe_rects.append(ir)

    if not safe_rects:
        return lines

    kept: List[Line] = []
    for ln in lines:
        if ln.x0 is None or ln.x1 is None:
            kept.append(ln)
            continue

        lr = pymupdf.Rect(ln.x0, ln.y0, ln.x1, ln.y1)
        if lr.is_empty:
            kept.append(ln)
            continue

        drop = False
        for ir in safe_rects:
            inter = lr & ir
            if inter.is_empty:
                continue

            # compute overlap fraction w.r.t. LINE dimensions (more stable than area tests)
            v_frac = inter.height / max(1e-6, lr.height)
            h_frac = inter.width / max(1e-6, lr.width)

            if v_frac >= min_v_overlap_frac and h_frac >= min_h_overlap_frac:
                drop = True
                break

        if not drop:
            kept.append(ln)

    return kept


def detect_footer_cutoff_y(
    lines: List[Line],
    *,
    page_height: float,
    start_frac: float = 0.55,
    min_gap: float = 45.0,
) -> Optional[float]:
    """
    Detect a footer/noise cutoff by looking for the largest vertical gap between consecutive lines
    after some fraction of the page (defaults to lower half).
    Returns cutoff y (lines below are considered footer/noise).
    """
    if len(lines) < 6:
        return None

    ys = [ln.y for ln in lines]
    pairs = list(zip(ys[:-1], ys[1:]))
    candidates: List[Tuple[float, float, float]] = []  # (gap, y_prev, y_next)
    for y_prev, y_next in pairs:
        if y_prev < start_frac * page_height:
            continue
        gap = y_next - y_prev
        if gap >= min_gap:
            candidates.append((gap, y_prev, y_next))

    if not candidates:
        return None

    # choose largest gap
    gap, y_prev, y_next = max(candidates, key=lambda t: t[0])
    return 0.5 * (y_prev + y_next)


def apply_footer_cutoff(
    lines: List[Line], cutoff_y: Optional[float]
) -> Tuple[List[Line], List[Line]]:
    """
    Split into (kept, footer) by cutoff_y.
    """
    if cutoff_y is None:
        return lines, []
    kept = [ln for ln in lines if ln.y < cutoff_y]
    foot = [ln for ln in lines if ln.y >= cutoff_y]
    return kept, foot


_WORDY_RE = re.compile(r"[A-Za-z]{3,}")


def detect_noise_cutoff_y(
    lines: List[Line],
    *,
    min_gap: float = 70.0,
    min_y: float = 200.0,
) -> Optional[float]:
    """
    Find a cutoff y by detecting a large vertical gap in the lower part of the page.
    This catches stamp/garbage zones like your y=343 -> 466 transition.
    """
    if len(lines) < 8:
        return None

    ys = [ln.y for ln in lines]
    best_gap = 0.0
    best_mid = None

    for a, b in zip(ys[:-1], ys[1:]):
        if a < min_y:
            continue
        gap = b - a
        if gap > best_gap and gap >= min_gap:
            best_gap = gap
            best_mid = 0.5 * (a + b)

    return best_mid


def apply_cutoff(
    lines: List[Line], cutoff_y: Optional[float]
) -> Tuple[List[Line], List[Line]]:
    if cutoff_y is None:
        return lines, []
    kept = [ln for ln in lines if ln.y < cutoff_y]
    cut = [ln for ln in lines if ln.y >= cutoff_y]
    return kept, cut
