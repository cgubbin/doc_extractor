from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pypdf import PdfReader

from patent_ingest.parse_front_page import (
    # Reuse your front-page cleaning + parsing
    dehyphenate,
    normalize_whitespace,
    strip_front_page_noise,
    parse_front_page,
)

# -----------------------------
# Page text extraction
# -----------------------------

# For non-front pages, you may want different stripping; keep simple for now.
_BODY_STRIP_PATTERNS = [
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]


def strip_body_noise(text: str) -> str:
    cleaned = text or ""
    for pat in _BODY_STRIP_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_page_text(reader: PdfReader, page_index: int, *, is_front_page: bool = False) -> str:
    page = reader.pages[page_index]
    t = page.extract_text() or ""
    t = dehyphenate(t)
    if is_front_page:
        t = strip_front_page_noise(t)  # preserves patent header line
    else:
        t = strip_body_noise(t)
    t = normalize_whitespace(t)
    return t


def extract_all_pages_text(reader: PdfReader) -> List[str]:
    out: List[str] = []
    for i in range(len(reader.pages)):
        out.append(extract_page_text(reader, i, is_front_page=(i == 0)))
    return out


# -----------------------------
# Signals / detectors
# -----------------------------

# Common in drawing pages: "Sheet 1 of 6"
DRAWING_SHEET_PAT = re.compile(r"\bSheet\s+(\d+)\s+of\s+(\d+)\b", re.IGNORECASE)

# Some front-matter spillover signals
REFS_CONTINUED_PAT = re.compile(r"\(\s*Continued\s*\)|\bContinued\b", re.IGNORECASE)
REFS_START_PAT = re.compile(r"\(\s*56\s*\)\s*References\s+Cited\b", re.IGNORECASE)
RELATED_APP_CONTINUED_PAT = re.compile(
    r"\bRelated\s+U\.S\.\s+Application\s+Data\b.*\bContinued\b", re.IGNORECASE
)

# A simple heuristic: pages containing these are almost certainly still front matter
FRONT_MATTER_KEYWORDS = [
    re.compile(r"\(\s*56\s*\)\s*References\s+Cited\b", re.IGNORECASE),
    re.compile(r"\bU\.S\.\s*PATENT\s*DOCUMENTS\b", re.IGNORECASE),
    re.compile(r"\bFOREIGN\s+PATENT\s+DOCUMENTS\b", re.IGNORECASE),
    re.compile(r"\bOTHER\s+PUBLICATIONS\b", re.IGNORECASE),
    re.compile(r"\bRelated\s+U\.S\.\s+Application\s+Data\b", re.IGNORECASE),
    re.compile(r"\bPrimary\s+Examiner\b", re.IGNORECASE),
]


def find_drawing_start_page(
    pages_text: List[str],
    *,
    reported_drawing_sheets: Optional[int],
) -> Optional[int]:
    """
    Best effort:
      1) Find the first page containing "Sheet X of Y". Prefer X=1.
      2) If not found, fall back to page 1 (immediately after front matter) if reported_drawing_sheets is known.
    """
    first_any = None
    first_sheet1 = None

    for i, t in enumerate(pages_text):
        if i == 0:
            continue
        m = DRAWING_SHEET_PAT.search(t or "")
        if m:
            if first_any is None:
                first_any = i
            try:
                x = int(m.group(1))
                if x == 1 and first_sheet1 is None:
                    first_sheet1 = i
            except Exception:
                pass

    if first_sheet1 is not None:
        return first_sheet1
    if first_any is not None:
        return first_any

    if reported_drawing_sheets is not None and len(pages_text) > 1:
        # fallback assumption: drawings start right after front matter, but only if we cannot detect
        return 1

    return None


def page_looks_like_front_matter(t: str) -> bool:
    if not t:
        return False
    for pat in FRONT_MATTER_KEYWORDS:
        if pat.search(t):
            return True
    return False


def compute_front_matter_page_count(
    pages_text: List[str],
    drawing_start_page: Optional[int],
) -> int:
    """
    Front matter always includes page 0.
    If we can detect drawing_start_page, front matter is everything before it.
    Otherwise, we assume front matter is just page 0.
    """
    if drawing_start_page is None:
        return 1
    return max(1, drawing_start_page)


# -----------------------------
# Reference-region extraction across front matter pages
# -----------------------------

ABSTRACT_HEAD_PAT = re.compile(
    r"\(\s*57\s*\)\s*ABSTRACT\b|^\s*ABSTRACT\b", re.IGNORECASE | re.MULTILINE
)


def slice_references_from_page_text(page_text: str) -> Optional[str]:
    """
    Slice references from a single page:
      start after (56) References Cited
      end at (57) ABSTRACT if present (rare on continuation pages), else end of page
    """
    m = REFS_START_PAT.search(page_text or "")
    if not m:
        return None
    start = m.end()
    end = len(page_text)
    m_abs = ABSTRACT_HEAD_PAT.search(page_text or "")
    if m_abs and m_abs.start() > start:
        end = m_abs.start()
    return (page_text[start:end]).strip()


def extract_references_region_across_pages(
    pages_text: List[str], front_matter_pages: List[int]
) -> Dict[str, Any]:
    """
    Build a refs region across front matter pages:
      - start at first page with (56)
      - include subsequent pages if they contain (56) again OR appear to be a continuation (Continued) and contain references headings.
    """
    refs_parts: List[str] = []
    pages_used: List[int] = []

    started = False
    for i in front_matter_pages:
        t = pages_text[i] or ""
        part = slice_references_from_page_text(t)

        if part is not None:
            refs_parts.append(part)
            pages_used.append(i)
            started = True
            continue

        # If already started, include likely continuation pages that contain references headings
        if started:
            if REFS_CONTINUED_PAT.search(t) or page_looks_like_front_matter(t):
                # Include entire page as continuation (best effort)
                refs_parts.append(t)
                pages_used.append(i)

    return {
        "raw": "\n\n".join([p for p in refs_parts if p]).strip(),
        "pages_used": pages_used,
    }


# -----------------------------
# Main pipeline
# -----------------------------


def ingest_patent_pdf(path: str) -> Dict[str, Any]:
    """
    Orchestrates:
      - page text extraction
      - front page parse (metadata, counts)
      - determine drawing start & allocate drawing pages
      - determine body pages
      - extract references region across front matter pages

    Returns a structured object suitable for downstream body/claims parsing.
    """
    reader = PdfReader(path)
    pages_text = extract_all_pages_text(reader)
    n_pages = len(pages_text)

    # Parse front page (page 0 text)
    front_page = parse_front_page(pages_text[0])

    reported_counts = front_page.get("reported_counts") or {}
    reported_drawing_sheets = reported_counts.get("reported_drawing_sheet_count")
    reported_claim_count = reported_counts.get("reported_claim_count")

    # Detect drawings start by "Sheet X of Y"
    drawing_start = find_drawing_start_page(
        pages_text, reported_drawing_sheets=reported_drawing_sheets
    )

    # Front matter pages: everything before drawing_start (if known)
    front_matter_count = compute_front_matter_page_count(pages_text, drawing_start)
    front_matter_pages = list(range(0, min(front_matter_count, n_pages)))

    # Drawing pages: start at drawing_start for D pages (if known)
    drawing_pages: List[int] = []
    if drawing_start is not None and reported_drawing_sheets is not None:
        end = min(drawing_start + int(reported_drawing_sheets), n_pages)
        drawing_pages = list(range(drawing_start, end))

    # Body pages: after drawings (if drawings computed), else after front matter
    if drawing_pages:
        body_start = drawing_pages[-1] + 1
    else:
        body_start = front_matter_pages[-1] + 1 if front_matter_pages else 1
    body_pages = list(range(body_start, n_pages))

    # References region across front matter pages (prevents picking up "Prior Publication Data")
    references_region = extract_references_region_across_pages(pages_text, front_matter_pages)

    # QA diagnostics for pipeline
    qa_warnings: List[str] = []
    qa_info: Dict[str, Any] = {}

    if reported_drawing_sheets is None:
        qa_warnings.append("missing_reported_drawing_sheet_count")

    if drawing_start is None and reported_drawing_sheets is not None:
        qa_warnings.append("drawing_start_not_detected_used_fallback")

    if (
        reported_drawing_sheets is not None
        and drawing_pages
        and len(drawing_pages) != int(reported_drawing_sheets)
    ):
        qa_warnings.append("drawing_page_count_mismatch_reported")

    if REFS_START_PAT.search(pages_text[0] or "") and not references_region["raw"]:
        qa_warnings.append("references_expected_but_empty")

    # Merge front page QA with pipeline QA (keep separate namespaces to avoid confusion)
    qa_info["reported_claim_count"] = reported_claim_count
    qa_info["reported_drawing_sheet_count"] = reported_drawing_sheets
    qa_info["front_matter_pages"] = front_matter_pages
    qa_info["drawing_pages"] = drawing_pages
    qa_info["body_pages"] = body_pages
    qa_info["references_pages_used"] = references_region.get("pages_used", [])

    return {
        "path": path,
        "pages_text": pages_text,  # optional; keep if you want debugging, or drop later
        "front_page": front_page,
        "front_matter": {
            "pages": front_matter_pages,
            "text": "\n\n".join(
                [pages_text[i] for i in front_matter_pages if pages_text[i]]
            ).strip(),
            "references_region": references_region,
        },
        "drawings": {
            "pages": drawing_pages,
            "reported_drawing_sheets": reported_drawing_sheets,
        },
        "body": {
            "pages": body_pages,
            "text": "\n\n".join([pages_text[i] for i in body_pages if pages_text[i]]).strip(),
        },
        "qa": {
            "warnings": qa_warnings,
            "info": qa_info,
        },
    }


if __name__ == "__main__":
    # Minimal smoke-test when run directly.
    # Example:
    #   python patent_front_page.py /path/to/granted.pdf
    import sys

    try:
        from pypdf import PdfReader
    except Exception:
        print("pypdf is required for CLI usage. Install with: pip install pypdf")
        raise

    if len(sys.argv) != 2:
        print("Usage: python patent_front_page.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    pdf = ingest_patent_pdf(pdf_path)
    print(pdf["qa"])
