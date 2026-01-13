import re
from typing import Optional
from typing import List, Tuple
from pypdf import PdfReader

NEG_TEXT_PAT = re.compile(
    r"\b(References\s+Cited|U\.S\.\s*PATENT\s*DOCUMENTS|FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS|\(\s*57\s*\)\s*ABSTRACT|\bClaims\b)\b",
    re.IGNORECASE,
)
SHEET_PAT = re.compile(r"\bSheet\s+\d+\s+of\s+\d+\b", re.IGNORECASE)
FIG_PAT = re.compile(r"\bFIG\.?\s*\d+\b", re.IGNORECASE)


SHEET_OF_N_PAT = re.compile(
    r"\bSheet\b\s*(\d{1,3})\s*\bof\b\s*(\d{1,3})\b",
    re.IGNORECASE,
)


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def infer_drawings_start_index_by_sheet_header(
    reader: PdfReader,
    expected_sheets: int,
    *,
    search_start: int = 1,
    search_limit: int = 25,
) -> Optional[int]:
    """
    Prefer explicit 'Sheet i of n' markers to locate the drawings block.
    Assumes drawings sheets are consecutive pages once started.
    """
    n_pages = len(reader.pages)
    if expected_sheets <= 0 or n_pages <= 1:
        return None

    # Scan a bounded range
    stop = min(n_pages, search_start + search_limit)

    sheet_hits: List[Tuple[int, int, int]] = []  # (page_index, i, n)
    for idx in range(search_start, stop):
        txt = reader.pages[idx].extract_text() or ""
        txt = normalize_ws(txt)
        m = SHEET_OF_N_PAT.search(txt)
        if m:
            i = int(m.group(1))
            n = int(m.group(2))
            sheet_hits.append((idx, i, n))

    if not sheet_hits:
        return None

    # Choose the earliest hit that is consistent with expected_sheets if available
    # (Some patents print "Sheet 1 of N". Prefer those.)
    for idx, i, n in sheet_hits:
        if i == 1 and (n == expected_sheets or expected_sheets is None):
            return idx

    # Otherwise choose earliest hit with n == expected_sheets
    for idx, i, n in sheet_hits:
        if n == expected_sheets:
            return idx

    # Fallback: earliest hit
    return sheet_hits[0][0]


def infer_drawings_start_index(
    reader: PdfReader,
    expected_sheets: int,
    *,
    search_start: int = 1,
    search_limit: int = 25,
) -> Optional[int]:
    """
    Two-stage inference:
      1) Prefer 'Sheet i of n' marker (high precision)
      2) Fall back to drawing-like scoring (higher recall)
    """
    s = infer_drawings_start_index_by_sheet_header(
        reader,
        expected_sheets,
        search_start=search_start,
        search_limit=search_limit,
    )
    if s is not None:
        return s

    # Fall back to your previous scoring-based inference
    return infer_drawings_start_index_by_score(reader, expected_sheets)  # your existing function


def _count_images(page) -> int:
    # Counts image XObjects; safe even if structure varies
    try:
        res = page.get("/Resources") or {}
        xobj = res.get("/XObject")
        if not xobj:
            return 0
        count = 0
        for _, obj in xobj.items():
            try:
                o = obj.get_object()
                if o.get("/Subtype") == "/Image":
                    count += 1
            except Exception:
                continue
        return count
    except Exception:
        return 0


def _content_length(page) -> int:
    # Approximates graphics density without rendering
    try:
        c = page.get_contents()
        if c is None:
            return 0
        if isinstance(c, list):
            return sum(len(x.get_data() or b"") for x in c)
        return len(c.get_data() or b"")
    except Exception:
        return 0


def drawing_page_score(page) -> float:
    txt = page.extract_text() or ""
    txt_len = len(txt.strip())
    img_count = _count_images(page)
    clen = _content_length(page)

    if NEG_TEXT_PAT.search(txt):
        return -10.0

    score = 0.0

    # low text is good
    if txt_len <= 300:
        score += 2.0
    elif txt_len <= 800:
        score += 1.0
    else:
        score -= 2.0

    # images help
    if img_count >= 1:
        score += 2.0

    # heavy content stream often indicates drawings (vector)
    if clen >= 50_000:
        score += 2.0
    elif clen >= 10_000:
        score += 1.0

    # optional textual markers
    if SHEET_PAT.search(txt):
        score += 2.0
    if FIG_PAT.search(txt):
        score += 1.0

    return score


def infer_drawings_start_index_by_score(
    reader: PdfReader,
    expected_sheets: int,
    *,
    search_start: int = 1,
    search_limit: int = 12,
    per_page_threshold: float = 2.0,
    allow_weak_pages: int = 1,
) -> Optional[int]:
    n = len(reader.pages)
    if expected_sheets <= 0 or n <= 1:
        return None

    last_start = min(n - expected_sheets, search_limit)
    scores = [None] * n
    for i in range(search_start, min(n, search_limit + expected_sheets + 2)):
        scores[i] = drawing_page_score(reader.pages[i])

    print(scores)

    for s in range(search_start, last_start + 1):
        window = scores[s : s + expected_sheets]
        print(window)
        if any(v is None for v in window):
            continue
        weak = sum(1 for v in window if v < per_page_threshold)

        if weak <= allow_weak_pages:
            return s

    return None
