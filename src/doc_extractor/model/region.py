from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import statistics
import re

from doc_extractor.model.model import Col, Line


from typing import Literal

SplitterMode = Literal["strict_metadata", "generic"]

# Strong drawing cues
SHEET_RE = re.compile(r"\b(?:sheet|page)\s+\d+\s+(?:of|/)\s+\d+\b", re.IGNORECASE)
PAP_RE = re.compile(r"\bpatent application publication\b", re.IGNORECASE)
FIG_RE = re.compile(r"\bfig\.?\s*\d+\b", re.IGNORECASE)

# Admin cues
CERT_RE = re.compile(r"\bcertificate of correction\b", re.IGNORECASE)
USPTO_RE = re.compile(
    r"\bunited states patent and trademark office\b|\buspto\b", re.IGNORECASE
)

# INID-ish cue: "(54)" etc. (standalone or inline)
INID_INLINE_RE = re.compile(r"^\(\s*\d{2}\s*\)\b")


# Utility: pull a small "top zone" blob
def _top_zone_blob(
    L: List["Line"],
    R: List["Line"],
    *,
    page_height: float,
    zone_frac: float = 0.18,
    zone_height: float = 150.0,
) -> str:
    zone_y = min(zone_height, zone_frac * page_height)
    top = [ln for ln in (*L, *R) if ln.y <= zone_y and (ln.text or "").strip()]
    top.sort(key=lambda ln: ln.y)
    return " ".join(ln.text.strip() for ln in top)


def _count_inid_labels(lines: List["Line"], *, y_max: float | None = None) -> int:
    c = 0
    for ln in lines:
        if y_max is not None and ln.y > y_max:
            continue
        t = (ln.text or "").strip()
        if not t:
            continue
        if INID_INLINE_RE.match(t):
            c += 1
    return c


def choose_header_splitter(
    L: List["Line"],
    R: List["Line"],
    *,
    page_height: float,
    # tuneables
    drawing_top_zone_frac: float = 0.20,
    drawing_top_zone_height: float = 170.0,
    min_inids_top: int = 3,
) -> SplitterMode:
    """
    Decide whether to use strict metadata header splitting or the generic geometric splitter,
    based only on raw line lists.

    Routing principle:
    - If strong drawing evidence -> generic (drawing)
    - Else -> strict_metadata (prevents prose from being put into header)
    """
    if not (L or R):
        return "strict_metadata"

    top_blob = _top_zone_blob(
        L,
        R,
        page_height=page_height,
        zone_frac=drawing_top_zone_frac,
        zone_height=drawing_top_zone_height,
    )

    # 1) Drawing pages: very strong signals
    # Typical drawing header has: "Patent Application Publication" + "Mar. 3, 2011 Sheet X of Y" + "US .... A1"
    if SHEET_RE.search(top_blob):
        return "generic"
    if PAP_RE.search(top_blob) and ("US" in top_blob.upper()):
        return "generic"
    # Additional weak cue: "Fig. 1" near top (rare) + sheet/page
    if FIG_RE.search(top_blob) and SHEET_RE.search(top_blob):
        return "generic"

    # 2) Admin/certificate pages: also better served by generic (often single-column, odd formatting)
    if CERT_RE.search(top_blob) or USPTO_RE.search(top_blob):
        return "generic"

    # 3) INID-heavy pages: strict_metadata is still safe, but you may prefer generic if you
    # want to preserve all top matter geometry. Choose based on your preference.
    # If you want INID pages to use generic, enable this block.
    top_y = min(0.35 * page_height, 260.0)
    inids_top = _count_inid_labels([*L, *R], y_max=top_y)
    if inids_top >= min_inids_top:
        # Option A: treat INID pages as generic
        return "generic"
        # Option B: strict metadata everywhere non-drawing
        # return "strict_metadata"

    # Default: strict metadata to guarantee no prose in header
    return "strict_metadata"


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


import re


_RX_US_PUB = re.compile(r"\bUS\s*\d{4}\s*/?\s*\d{6,8}\s*[A-Z0-9]{1,2}\b", re.IGNORECASE)
_RX_US_GRANT = re.compile(r"\bUS\s*\d[\d,\s]*\s*[A-Z0-9]{1,2}\b", re.IGNORECASE)
_RX_KIND = re.compile(r"\b(?:A1|A2|A9|B1|B2)\b", re.IGNORECASE)
_RX_DATE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE,
)
_RX_SHEET = re.compile(r"\b(?:sheet|page)\s+\d+\s+(?:of|/)\s+\d+\b", re.IGNORECASE)


def _looks_like_running_header(lines: List[Line]) -> bool:
    """
    True if the text looks like the small running header on body pages:
    patent id, date, page/sheet counter, kind.
    """
    if not lines:
        return False
    t = " ".join(ln.text for ln in lines if ln.text).strip()
    if not t:
        return False

    hits = 0
    if _RX_US_PUB.search(t) or _RX_US_GRANT.search(t):
        hits += 1
    if _RX_DATE.search(t):
        hits += 1
    if _RX_SHEET.search(t):
        hits += 1
    if _RX_KIND.search(t):
        hits += 1

    # conservative: require at least one strong signal, or 2 weak ones
    return hits >= 1


import re

_RX_US_PUB = re.compile(r"\bUS\s*\d{4}\s*/?\s*\d{6,8}\s*[A-Z0-9]{1,2}\b", re.IGNORECASE)
_RX_US_GRANT = re.compile(r"\bUS\s*\d[\d,\s]*\s*[A-Z0-9]{1,2}\b", re.IGNORECASE)
_RX_US_COMPACT = re.compile(r"\bUS\d{7,11}[A-Z0-9]{1,2}\b", re.IGNORECASE)
_RX_KIND = re.compile(r"\b(?:A1|A2|A9|B1|B2)\b", re.IGNORECASE)
_RX_DATE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\.?\s+\d{1,2},\s+\d{4}\b",
    re.IGNORECASE,
)
_RX_SHEET = re.compile(r"\b(?:sheet|page)\s+\d+\s+(?:of|/)\s+\d+\b", re.IGNORECASE)
_RX_PAP = re.compile(r"\bpatent application publication\b", re.IGNORECASE)


def _is_header_metadata_line(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    # Strong identifiers
    if _RX_US_PUB.search(t) or _RX_US_GRANT.search(t) or _RX_US_COMPACT.search(t):
        return True

    # Date / page counters
    if _RX_DATE.search(t) or _RX_SHEET.search(t):
        return True

    # "Patent Application Publication" (common on drawings, occasionally on body top)
    if _RX_PAP.search(t):
        return True

    # Kind token alone is too weak; avoid treating "B2" in a sentence as header
    # If you really want: require kind + some digits.
    if _RX_KIND.search(t) and re.search(r"\d", t):
        return True

    return False


def split_header_body_strict_metadata(
    L: List[Line],
    R: List[Line],
    *,
    page_height: float,
    header_zone_frac: float = 0.12,
    header_zone_height: float = 110.0,
) -> Tuple[Dict[Col, List[Line]], Dict[Col, List[Line]]]:
    """
    BODY-PAGE header splitter with a hard guarantee:
    header contains only running metadata lines; no prose.
    """
    zone_y = min(header_zone_height, header_zone_frac * page_height)

    hL, bL = [], []
    hR, bR = [], []

    for ln in L:
        if ln.y <= zone_y and _is_header_metadata_line(ln.text):
            hL.append(ln)
        else:
            bL.append(ln)

    for ln in R:
        if ln.y <= zone_y and _is_header_metadata_line(ln.text):
            hR.append(ln)
        else:
            bR.append(ln)

    # Optional: if you matched nothing, header empty; that's fine.
    return {"L": hL, "R": hR}, {"L": bL, "R": bR}


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
    mode: str = "auto",  # "auto" | "body" | "drawing"
    max_header_frac_body: float = 0.10,
    max_header_height_body: float = 80.0,
) -> Tuple[Dict[Col, List[Line]], Dict[Col, List[Line]]]:
    """
    Header/body split:
    - Drawing sheets: allow deeper header + gap refinement (old behavior).
    - Body pages: cap header and avoid swallowing section titles.
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

    # Decide mode if auto
    if mode == "auto":
        # If the clustered top band looks like running header metadata, treat as body header
        band_lines = [ln for ln in top_lines if band_lo <= ln.y <= band_hi]
        mode = "body" if _looks_like_running_header(band_lines) else "drawing"

    if mode == "body":
        # HARD CAP: header must remain small on body pages
        cap = min(max_header_height_body, max_header_frac_body * page_height)
        split_y = min(split_y, cap)

        # NO gap refinement for body pages (prevents swallowing headings / first paragraph)
        hL = [ln for ln in L if ln.y <= split_y]
        bL = [ln for ln in L if ln.y > split_y]
        hR = [ln for ln in R if ln.y <= split_y]
        bR = [ln for ln in R if ln.y > split_y]
        return {"L": hL, "R": hR}, {"L": bL, "R": bR}

    # --- drawing-mode: keep your existing refinement ---
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


# def split_header_body_generic(
#     L: List[Line],
#     R: List[Line],
#     *,
#     page_height: float,
#     top_frac: float = 0.22,
#     max_band_height: float = 30.0,
#     pad: float = 4.0,
#     gap_mult: float = 2.5,
#     min_gap: float = 24.0,
# ) -> Tuple[Dict[Col, List[Line]], Dict[Col, List[Line]]]:
#     """
#     Works for drawing sheets and body text pages.
#     """
#     if not (L or R):
#         return {"L": [], "R": []}, {"L": L, "R": R}
#
#     top_lines = _collect_top_lines(L, R, page_height, top_frac=top_frac)
#     if len(top_lines) < 2:
#         return {"L": [], "R": []}, {"L": L, "R": R}
#
#     band = _cluster_top_band(top_lines, max_band_height=max_band_height)
#     if band is None:
#         return {"L": [], "R": []}, {"L": L, "R": R}
#
#     band_lo, band_hi = band
#     split_y = band_hi + pad
#
#     # refine: look for first big gap AFTER header band (good on body text pages)
#     all_lines = sorted([*L, *R], key=lambda ln: ln.y)
#     scan = [
#         ln for ln in all_lines if ln.y <= 0.45 * page_height and ln.y >= band_lo - 2.0
#     ]
#     if len(scan) >= 6:
#         ys = [ln.y for ln in scan]
#         gaps = [
#             ys[i + 1] - ys[i] for i in range(len(ys) - 1) if (ys[i + 1] - ys[i]) > 0
#         ]
#         med = statistics.median(gaps) if gaps else 10.0
#         thresh = max(min_gap, gap_mult * med)
#         for i in range(len(scan) - 1):
#             if scan[i].y < split_y:
#                 continue
#             g = scan[i + 1].y - scan[i].y
#             if g >= thresh:
#                 split_y = scan[i].y + pad
#                 break
#
#     hL = [ln for ln in L if ln.y <= split_y]
#     bL = [ln for ln in L if ln.y > split_y]
#     hR = [ln for ln in R if ln.y <= split_y]
#     bR = [ln for ln in R if ln.y > split_y]
#     return {"L": hL, "R": hR}, {"L": bL, "R": bR}
#
#
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
