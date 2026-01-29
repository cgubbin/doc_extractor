import re
from typing import Dict, List, Tuple

Line = "Line"  # forward reference to avoid circular import
PageLayout = "PageLayout"  # forward reference to avoid circular import

# INID token like "(12)"
INID_TOKEN_RE = re.compile(r"\(\d{2}\)")

# Running header patterns on patents/applications
RUN_HEADER_RE = re.compile(
    r"(?:\bU\.S\.\s*Patent\b|"
    r"\bPatent\s+Application\s+Publication\b|"
    r"\bUS\s*\d[\d,\s/]*\s*[A-Z]\d\b|"  # e.g. US 7,629,993 B2 or US 2011/0054659 A1
    r"\bUS\s*\d{8,}\w*\b|"  # e.g. US20110054659A1
    r"\bSheet\s+\d+\s+of\s+\d+\b)",  # Sheet X of Y
    re.IGNORECASE,
)

PAGE_NUM_RE = re.compile(r"^\s*\d+\s*$")


def split_cross_gutter_header_lines(
    header: Dict[str, List["Line"]],
    *,
    page_width: float,
    mid_gutter: float = 10.0,
    tol: float = 2.0,
) -> Dict[str, List["Line"]]:
    """
    Repair rare cases where a single header Line spans across the gutter and contains multiple INID labels,
    e.g. "(12) ... (10) Pub. No.: ..."

    We split by the second INID token and move the second part into the right header.
    This is intentionally conservative: it only triggers on cross-gutter lines with >=2 INID tokens.
    """
    mid_x = page_width / 2.0
    left_max = mid_x - (mid_gutter / 2.0) - tol
    right_min = mid_x + (mid_gutter / 2.0) + tol

    out_L: List["Line"] = []
    out_R: List["Line"] = list(header["R"])

    for ln in header["L"]:
        x0 = getattr(ln, "x0", None)
        x1 = getattr(ln, "x1", None)
        txt = (ln.text or "").strip()

        if x0 is None or x1 is None or not txt:
            out_L.append(ln)
            continue

        spans_gutter = (x0 < left_max) and (x1 > right_min)
        if not spans_gutter:
            out_L.append(ln)
            continue

        hits = list(INID_TOKEN_RE.finditer(txt))
        if len(hits) < 2:
            out_L.append(ln)
            continue

        # split at the start of 2nd INID
        cut = hits[1].start()
        left_txt = txt[:cut].strip()
        right_txt = txt[cut:].strip()

        # Create two synthetic lines; keep y geometry, clamp x ranges to each side
        if left_txt:
            out_L.append(
                type(ln)(
                    y0=ln.y0,
                    y1=ln.y1,
                    x0=ln.x0,
                    x1=min(ln.x1, left_max),
                    text=left_txt,
                )
            )
        if right_txt:
            out_R.append(
                type(ln)(
                    y0=ln.y0,
                    y1=ln.y1,
                    x0=max(ln.x0, right_min),
                    x1=ln.x1,
                    text=right_txt,
                )
            )
        # NOTE: do not keep original merged ln

    out_R.sort(key=lambda l: getattr(l, "y0", getattr(l, "y", 0.0)))
    return {"L": out_L, "R": out_R}


def split_header_body_running(
    streams: Dict[str, List["Line"]],
    *,
    page_height: float,
    top_band: float = 85.0,
    bottom_band: float = 60.0,
) -> Tuple[Dict[str, List["Line"]], Dict[str, List["Line"]]]:
    """
    Alternative splitter for pages where content starts very near the top (claims pages / dense body pages),
    where gap-based 'generic' header splitting can swallow content.

    Strategy:
      - Treat lines in top band that match RUN_HEADER_RE (or look like page numbers) as header.
      - Treat remaining lines as body.
      - Footer: drop pure page numbers in bottom band (optional).
    """
    header = {"L": [], "R": []}
    body = {"L": [], "R": []}

    for col in ("L", "R"):
        for ln in streams[col]:
            y0 = getattr(ln, "y0", None)
            if y0 is None:
                # fallback
                y0 = getattr(ln, "y", 0.0)

            t = (ln.text or "").strip()
            if not t:
                continue

            in_top = y0 < top_band
            in_bottom = y0 > (page_height - bottom_band)

            if in_top and (RUN_HEADER_RE.search(t) or PAGE_NUM_RE.match(t)):
                header[col].append(ln)
                continue

            if in_bottom and PAGE_NUM_RE.match(t):
                # drop footer page number noise
                continue

            body[col].append(ln)

    return header, body


def should_fallback_to_running_split(
    streams: Dict[str, List["Line"]],
    header: Dict[str, List["Line"]],
    body: Dict[str, List["Line"]],
) -> bool:
    """
    Decide whether generic split likely failed (e.g. claims page swallowed into header).
    """
    total = len(streams["L"]) + len(streams["R"])
    body_n = len(body["L"]) + len(body["R"])
    header_n = len(header["L"]) + len(header["R"])

    # NEW: hard failure case
    if total > 0 and body_n == 0:
        return True

    # If there is substantial text overall, but body is implausibly empty, it's a strong signal.
    # (Your page 7 case typically ends up here.)
    if total >= 30 and body_n <= 6 and header_n >= (total - 6):
        return True

    # Another case: header got huge while body got tiny
    if total >= 40 and body_n <= 10 and header_n >= 30:
        return True

    return False


# FRONT_CONTINUATION_RE = re.compile(
#     r"\b(continued|prior publication data|related u\.s\. application data|references cited|field of classification search|other publications)\b",
#     re.IGNORECASE,
# )
#
# BODY_START_RE = re.compile(
#     r"^\s*(TECHNICAL FIELD|BACKGROUND( ART| OF THE INVENTION)?|SUMMARY|DETAILED DESCRIPTION|BRIEF DESCRIPTION OF THE DRAWINGS|CLAIMS)\s*$",
#     re.IGNORECASE,
# )
#
#
# def _page_text(layout, region="body", max_lines=120) -> str:
#     reg = getattr(layout, region)
#     parts = []
#     for col in ("L", "R"):
#         for ln in reg[col].lines[:max_lines]:
#             t = (ln.text or "").strip()
#             if t:
#                 parts.append(t)
#     return "\n".join(parts)
#
#
# def detect_front_matter_pages(
#     layouts: List["PageLayout"],
#     page_kinds: List[
#         str
#     ],  # output of per-page classify_page (e.g. "drawing","body","admin","unknown","inid")
# ) -> List[str]:
#     """
#     Upgrade page kinds so that INID/front-matter can span multiple pages until drawings or body start.
#     """
#
#     n = len(layouts)
#
#     # first drawing page (hard stop)
#     try:
#         first_drawing = page_kinds.index("drawing")
#     except ValueError:
#         first_drawing = n
#
#     # Find initial INID page(s) at the start
#     i = 0
#     while i < n and page_kinds[i] == "admin":
#         i += 1
#
#     if i >= n or page_kinds[i] != "inid":
#         # no title-page INIDs at start; nothing to extend
#         return page_kinds
#
#     # We have an INID start; extend forward until hard stop
#     j = i + 1
# while j < n and j < first_drawing:
#     if page_kinds[j] in ("drawing", "admin"):
#         break
#
#     body_txt = _page_text(layouts[j], "body")
#     hdr_txt = _page_text(layouts[j], "header")
#     txt = (hdr_txt + "\n" + body_txt).strip()
#
#     # Hard stop if clear body start headings/claims
#     # (use a few top lines)
#     top_lines = txt.splitlines()[:60]
#     if any(BODY_START_RE.match(ln.strip()) for ln in top_lines):
#         break
#
#     # If page looks like continuation/front matter, mark as inid-front continuation
#     if FRONT_CONTINUATION_RE.search(txt):
#         page_kinds[j] = (
#             "inid"  # treat as front matter continuation for your pipeline
#         )
#         j += 1
#         continue
#
#     # Otherwise, stop extension (don’t wrongly absorb real body pages)
#     break
#
# return page_kinds


import re
from typing import List

# Stop signals: real body starts
BODY_START_RE = re.compile(
    r"^\s*(TECHNICAL FIELD|FIELD|BACKGROUND( ART| OF THE INVENTION)?|SUMMARY( OF THE INVENTION)?|"
    r"DETAILED DESCRIPTION( OF THE EMBODIMENTS)?|BRIEF DESCRIPTION OF THE DRAWINGS|CLAIMS)\s*$",
    re.IGNORECASE,
)

WHAT_CLAIMED_RE = re.compile(r"\bwhat\s+is\s+claimed\s+is\b", re.IGNORECASE)
CLAIM_LINE_RE = re.compile(r"^\s*\d{1,3}\.\s+\S")  # "13. The method ..."

# Optional continuation hints (nice to have, not required)
FRONT_HINT_RE = re.compile(
    r"\b(continued|references cited|u\.s\. patent documents|other publications|primary examiner|assistant examiner|"
    r"related u\.s\. application data|prior publication data|field of classification search)\b",
    re.IGNORECASE,
)

_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS_RE.sub(" ", (s or "").replace("\u00a0", " ")).strip()


def _page_text(layout, *, max_lines: int = 200) -> List[str]:
    """Return a list of non-empty lines from header+body in reading bands, preserving line breaks."""
    out = []
    for region in ("header", "body"):
        reg = getattr(layout, region)
        for col in ("L", "R"):
            for ln in reg[col].lines[:max_lines]:
                t = _norm(getattr(ln, "text", "") or "")
                if t:
                    out.append(t)
    return out


def _is_body_start(lines: List[str]) -> bool:
    head = lines[:120]
    if any(BODY_START_RE.match(t) for t in head):
        return True
    joined = " ".join(head)
    if WHAT_CLAIMED_RE.search(joined):
        return True
    claim_like = sum(1 for t in head if CLAIM_LINE_RE.match(t))
    return claim_like >= 2


def detect_front_matter_pages(layouts, page_kinds: List[str]) -> List[str]:
    """
    If the document starts with an INID page, treat subsequent pages as front matter ("inid")
    by default until a hard stop (drawings/admin/body-start).
    This fixes multi-page front matter where page 2 has few/no INID tokens.
    """
    n = len(layouts)

    # find first drawing page (hard stop)
    try:
        kinds = [each.kind for each in page_kinds]
        first_drawing = kinds.index("drawing")
    except ValueError:
        first_drawing = n

    # Skip leading admin pages
    i = 0
    while i < n and page_kinds[i].kind == "admin":
        i += 1

    # Must start with inid to begin a front-matter run
    if i >= n or page_kinds[i].kind != "inid":
        return page_kinds

    # Extend run forward until hard stop
    j = i + 1
    while j < n and j < first_drawing:
        if page_kinds[j].kind in ("drawing", "admin"):
            break

        # If we already know it is body, stop extension
        if page_kinds[j].kind == "body":
            break

        lines = _page_text(layouts[j])
        # If the split produced almost nothing, still treat as continuation unless body-start is detected
        # (because empty body here usually means header/body splitting oddities).
        if lines and _is_body_start(lines):
            break

        # Soft hint: if it looks like front-matter, definitely keep it
        if FRONT_HINT_RE.search(" ".join(lines[:200]).lower()):
            page_kinds[j].kind = "inid"
            j += 1
            continue

        # Default behaviour: continue front matter unless body-start signals are present
        page_kinds[j].kind = "inid"
        j += 1

    return page_kinds


def smooth_drawing_runs(
    page_kinds: List[str],
    *,
    max_unknown_run: int = 2,
) -> List[str]:
    """
    Within a drawing run, relabel short unknown runs as drawing.

    A "drawing run" is a maximal segment containing drawings and unknowns where
    drawings occur on both sides, and unknown islands are short.
    """
    kinds = list(page_kinds)
    n = len(kinds)

    i = 0
    while i < n:
        if kinds[i].kind != "drawing":
            i += 1
            continue

        # start of run
        start = i
        i += 1
        while i < n and kinds[i].kind in ("drawing", "unknown"):
            i += 1
        end = i  # exclusive

        # In [start, end), relabel short unknown sequences as drawing
        j = start
        while j < end:
            if kinds[j].kind != "unknown":
                j += 1
                continue
            k = j
            while k < end and kinds[k].kind == "unknown":
                k += 1
            run_len = k - j
            # Only flip if unknown run is short AND there's a drawing somewhere after it in the run
            if run_len <= max_unknown_run and any(
                kinds[t].kind == "drawing" for t in range(k, end)
            ):
                for t in range(j, k):
                    kinds[t].kind = "drawing"
            j = k

    return kinds
