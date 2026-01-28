from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import statistics
import re

from patent_ingest.model.model import Col, Line

INID_START_RE = re.compile(r"^\(\s*\d+\s*\)")


def _collect_top_lines(
    L: List[Line], R: List[Line], page_height: float, top_frac: float
) -> List[Line]:
    y_top = top_frac * page_height
    all_lines = sorted([*L, *R], key=lambda ln: ln.y)
    return [ln for ln in all_lines if ln.y <= y_top]


def _cluster_top_band(
    lines: List[Line], *, max_band_height: float
) -> Optional[Tuple[float, float]]:
    """
    Find densest y-band within max_band_height (using line center y).
    """
    if len(lines) < 2:
        return None
    ys = sorted(ln.y for ln in lines)
    best = None  # (count, y_lo, y_hi)
    j = 0
    for i in range(len(ys)):
        while ys[i] - ys[j] > max_band_height:
            j += 1
        count = i - j + 1
        if best is None or count > best[0]:
            best = (count, ys[j], ys[i])
    if best is None or best[0] < 2:
        return None
    return (best[1], best[2])


def split_header_body_generic(
    L: List[Line],
    R: List[Line],
    *,
    page_height: float,
    top_frac: float = 0.22,
    max_band_height: float = 30.0,
    pad: float = 4.0,
    gap_mult: float = 2.5,
    min_gap: float = 24.0,
) -> Tuple[Dict[Col, List[Line]], Dict[Col, List[Line]]]:
    """
    Works for drawing sheets and body text pages.
    """
    if not (L or R):
        return {"L": [], "R": []}, {"L": L, "R": R}

    top_lines = _collect_top_lines(L, R, page_height, top_frac=top_frac)
    if len(top_lines) < 2:
        return {"L": [], "R": []}, {"L": L, "R": R}

    band = _cluster_top_band(top_lines, max_band_height=max_band_height)
    if band is None:
        return {"L": [], "R": []}, {"L": L, "R": R}

    band_lo, band_hi = band
    split_y = band_hi + pad

    # refine: look for first big gap AFTER header band (good on body text pages)
    all_lines = sorted([*L, *R], key=lambda ln: ln.y)
    scan = [
        ln for ln in all_lines if ln.y <= 0.45 * page_height and ln.y >= band_lo - 2.0
    ]
    if len(scan) >= 6:
        ys = [ln.y for ln in scan]
        gaps = [
            ys[i + 1] - ys[i] for i in range(len(ys) - 1) if (ys[i + 1] - ys[i]) > 0
        ]
        med = statistics.median(gaps) if gaps else 10.0
        thresh = max(min_gap, gap_mult * med)
        for i in range(len(scan) - 1):
            if scan[i].y < split_y:
                continue
            g = scan[i + 1].y - scan[i].y
            if g >= thresh:
                split_y = scan[i].y + pad
                break

    hL = [ln for ln in L if ln.y <= split_y]
    bL = [ln for ln in L if ln.y > split_y]
    hR = [ln for ln in R if ln.y <= split_y]
    bR = [ln for ln in R if ln.y > split_y]
    return {"L": hL, "R": hR}, {"L": bL, "R": bR}


def rescue_lines_from_header_into_body(
    header: Dict[Col, List[Line]],
    body: Dict[Col, List[Line]],
    *,
    # rescue only very near the first INID label on that page (e.g. title above (54))
    target_inid: int = 54,
    rescue_lines: int = 4,
    rescue_dy: float = 20.0,
) -> Tuple[Dict[Col, List[Line]], Dict[Col, List[Line]]]:
    """
    Optional: If an INID label exists in the body, pull a few lines just above it from the header.
    This avoids using the INID as the split anchor (we don't), but still captures the "prefix above label" pattern.
    """
    anchor = f"({target_inid})"

    # find anchor y in body across both columns
    y_anchor = None
    for ln in sorted([*body["L"], *body["R"]], key=lambda x: x.y):
        t = ln.text.strip()
        if t == anchor or t.startswith(anchor):
            y_anchor = ln.y
            break

    if y_anchor is None:
        return header, body

    def rescue(col: Col) -> None:
        nonlocal header, body
        hdr = header[col]
        rescued: List[Line] = []
        for ln in reversed(hdr):
            if len(rescued) >= rescue_lines:
                break
            dy = y_anchor - ln.y
            if dy <= 0 or dy > rescue_dy:
                break
            t = ln.text.strip()
            if not t:
                continue
            # don't cross other INID labels
            if INID_START_RE.match(t):
                break
            rescued.append(ln)

        if rescued:
            rescued.reverse()
            header = {**header, col: [ln for ln in hdr if ln not in rescued]}
            body = {**body, col: rescued + body[col]}

    rescue("L")
    rescue("R")
    return header, body
