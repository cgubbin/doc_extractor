"""
parse_front_page.py

Front (and front-matter) parsing for US granted patent PDFs extracted with pypdf.

Key features (updated):
- Robust metadata extraction even when INID slicing fails (regex fallbacks for Appl No, Filed, Date of Patent).
- Assignee cleaning stops before PTA/disclaimer boilerplate (e.g., "Subject to any disclaimer, the term of this ...").
- Cited US patents extracted by *region* (from (56) References Cited), preventing contamination by "Prior Publication Data".
- Supports references continuation onto page 2+ by allowing parse_front_matter(pages_text=[...]).
- Title extraction robust to column interleaving (handles (56) label intruding mid-title).
- Abstract extraction returns text only (excludes "(57) ABSTRACT" heading).
- QA diagnostics: actionable warnings + info counts.

Typical usage:
    from pypdf import PdfReader
    from patent_ingest.parse_front_page import extract_page0_text, parse_front_page, parse_front_matter

    reader = PdfReader("US9587932B2.pdf")
    page0 = extract_page0_text(reader)
    front = parse_front_page(page0)

Better usage for patents where references continue onto page 2:
    pages_text = [extract_page_text(reader, i) for i in range(min(3, len(reader.pages)))]
    front = parse_front_matter(pages_text)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from patent_ingest.model.document import (
    MultiPage,
    TwoColumn,
    Column,
)
from patent_ingest.model.mapping import (
    linearize,
    global_range_to_where,
    trim_global_range,
)


class PatentNumber:
    def __init__(self, raw: str):
        self.raw = raw
        self.normalized = normalize_us_patent_header(raw)
        self.digits = normalize_patent_number_digits(raw)

    def __str__(self) -> str:
        return self.normalized or self.raw or ""

    def kind_code(self) -> Optional[str]:
        if not self.normalized:
            return None
        m = KIND_CODE_PAT.search(self.raw)
        return m.group(1) if m else None


# =============================================================================
# Cleaning helpers (front page)
# =============================================================================

# On the front page, we intentionally do NOT strip the "US 7,629,993 B2" line.
_FRONT_STRIP_PATTERNS = [
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]


def dehyphenate(text: str) -> str:
    # Join words split by hyphen at line end: "inspec-\n tion" -> "inspection"
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text or "")


def normalize_whitespace(text: str) -> str:
    text = (text or "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_front_page_noise(text: str) -> str:
    cleaned = text or ""
    for pat in _FRONT_STRIP_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _cut_at_heading(s: str, pat: re.Pattern) -> str:
    if not s:
        return s
    m = pat.search(s)
    return s[: m.start()].strip() if m else s.strip()


def normalize_punctuation_spacing(s: str) -> str:
    """
    Fix common PDF-extraction spacing artifacts:
      - "Oct . 20 , 2016" -> "Oct. 20, 2016"
      - "Nigel P . Smith" -> "Nigel P. Smith"
      - "Milipatis , CA" -> "Milipatis, CA"
    Does NOT attempt spelling correction.
    """
    if not s:
        return s
    t = s

    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()

    # Remove spaces before common punctuation
    t = re.sub(r"\s+([,.;:)-])", r"\1", t)

    # Remove spaces after brackets
    t = re.sub(r"([(-])\s*", r"\1", t)

    # Ensure a single space after punctuation when appropriate
    # (Avoid touching decimals/abbreviations too aggressively.)
    t = re.sub(r"([,;:])([^\s])", r"\1 \2", t)

    # Fix spaced month abbreviations: "Oct .", "Sept ."
    t = re.sub(
        r"\b([A-Za-z]{3,4})\.\s*", lambda m: m.group(0), t
    )  # no-op but keeps structure clear

    return t


# =============================================================================
# pypdf integration helpers
# =============================================================================


def extract_page0_text(pdf_reader: Any) -> str:
    """
    Extract and clean page 0 text from a pypdf PdfReader.
    """
    # page0 = pdf_reader.pages[0]
    t = TwoColumn(pdf_reader, 0) or ""
    # t = t.pipe(dehyphenate, strip_front_page_noise, normalize_whitespace)
    return t


def extract_front_matter_text(
    pdf_reader: Any, page_index: int, *, is_front_page: bool = False
) -> str:
    """
    Extract and clean a page from a pypdf PdfReader.
    For now, use the same cleaning approach; callers may add body-specific stripping later.
    """
    # page = pdf_reader.pages[page_index]
    # t = page.extract_text() or ""
    t = TwoColumn(pdf_reader, page_index) or ""
    # t = t.pipe(dehyphenate)
    # if is_front_page or page_index == 0:
    # t = t.pipe(strip_front_page_noise)
    # t = t.pipe(normalize_whitespace)
    return t


# =============================================================================
# Generic helpers
# =============================================================================


def normalize_whitespace_basic(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def strip_leading_label(text: str, labels: List[str]) -> str:
    """
    Removes one of the provided labels from the beginning of a string, if present.
    Example: "Appl. No.: 15/142,864" -> "15/142,864"
    """
    t = (text or "").strip()
    for lab in labels:
        pat = re.compile(rf"^\s*{re.escape(lab)}\s*[:\-]?\s*", re.IGNORECASE)
        if pat.search(t):
            return pat.sub("", t).strip()
    return t


# =============================================================================
# INID parsing (best-effort)
# =============================================================================

INID_MARKER_PAT = re.compile(r"\(\s*(\d{2})\s*\)")  # e.g., "(54)"


def parse_inid_blocks(front_text: str) -> Dict[str, Dict[str, Any]]:
    """
    Returns dict: code -> { "text": str, "span": {"start": int, "end": int} }
    NOTE: Due to column interleaving, INID slices may be imperfect. We use them as hints.
    """
    matches = list(INID_MARKER_PAT.finditer(front_text))
    blocks: Dict[str, Dict[str, Any]] = {}
    for i, m in enumerate(matches):
        code = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(front_text)
        value = front_text[start:end].strip()
        if code not in blocks and value:
            blocks[code] = {"text": value, "span": {"start": start, "end": end}}
    return blocks


INID_MARKER_PAT = re.compile(r"\(\s*(\d{2})\s*\)")


def parse_inid_blocks_doc(
    doc: MultiPage,
    *,
    sep: str = "\n",
    order: Tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Dict[str, Dict[str, Any]]:
    """
    Returns dict: code -> { "text": str, "where": Span|MultiSpan, "global": (start,end) }
    'where' points into the original (page,column,offset) coordinate system.

    NOTE: Since your PDF extraction may interleave columns imperfectly, this is still a heuristic—
    but now spans are truthful about where the text came from.
    """
    linear_text, segments = linearize(doc, sep=sep, order=order)
    matches = list(INID_MARKER_PAT.finditer(linear_text))

    blocks: Dict[str, Dict[str, Any]] = {}
    for i, m in enumerate(matches):
        code = m.group(1)

        # block payload starts after marker, ends at next marker (or EOF)
        raw_start = m.end()
        raw_end = matches[i + 1].start() if i + 1 < len(matches) else len(linear_text)
        # Compute trimmed range so where matches the stored text exactly
        t_start, t_end = trim_global_range(linear_text, raw_start, raw_end)

        if t_end <= t_start:
            continue  # block contains only whitespace

        value = linear_text[t_start:t_end]
        if code in blocks or not value:
            continue

        where = global_range_to_where(t_start, t_end, segments)

        blocks[code] = {
            "text": value,
            "where": where,  # now aligned with "text"
            "global": (t_start, t_end),
        }

    return blocks


# =============================================================================
# Dates
# =============================================================================

_MONTH_FIX = {
    "Jan.": "Jan",
    "Feb.": "Feb",
    "Mar.": "Mar",
    "Apr.": "Apr",
    "Jun.": "Jun",
    "Jul.": "Jul",
    "Aug.": "Aug",
    "Sep.": "Sep",
    "Sept.": "Sep",
    "Oct.": "Oct",
    "Nov.": "Nov",
    "Dec.": "Dec",
}


def remove_whitespace(s: str) -> str:
    return re.sub(r"\s*", "", (s or ""))


def parse_uspto_date_to_iso(raw: str) -> Optional[str]:
    """
    Accepts strings like "Dec. 8, 2009" or "December 8, 2009".
    Returns ISO date "2009-12-08" or None.
    """
    if not raw:
        return None
    s = normalize_whitespace_basic(raw)
    s = normalize_punctuation_spacing(s)
    for k, v in _MONTH_FIX.items():
        s = s.replace(k, v)

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.date().isoformat()
        except ValueError:
            pass
    return None


# =============================================================================
# Patent number normalization
# =============================================================================

PATENT_HEADER_PAT = re.compile(
    r"\bUS\s+[\d,\s]{7,15}\s+[A-Z]\d\b"
)  # e.g., "US 9,587,932 B2"
KIND_CODE_PAT = re.compile(r"\b([A-Z]\d)\b")


def normalize_patent_number_digits(s: str) -> Optional[str]:
    """
    Extract digit-only patent number from strings like:
      "US 9,587,932 B2" -> "9587932"
    """
    s = normalize_punctuation_spacing(s)

    if not s:
        return None
    m = re.search(r"\b(\d{1,2}),\s*(\d{3}),\s*(\d{3})\b", s)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    m = re.search(r"\b(\d{7,8})\b", s)
    return m.group(1) if m else None


def normalize_us_patent_header(raw: str) -> Optional[str]:
    """
    "US 9,587,932 B2" -> "US9587932B2"
    """
    if not raw:
        return None
    digits = normalize_patent_number_digits(raw)
    if not digits:
        return None
    mk = KIND_CODE_PAT.search(raw)
    kind = mk.group(1) if mk else ""
    return f"US{digits}{kind}"


def comma_format_us_patent(digits: str) -> str:
    if not digits or not digits.isdigit():
        return digits
    return f"{int(digits):,}"


# =============================================================================
# Counts line (claims, drawing sheets)
# =============================================================================

REPORTED_COUNTS_PAT = re.compile(
    r"\b(\d+)\s+Claims?\s*,\s*(\d+)\s+Drawing\s+Sheets?\b",
    re.IGNORECASE,
)


def extract_reported_counts(front_text: str) -> Optional[Dict[str, Any]]:
    m = REPORTED_COUNTS_PAT.search(front_text or "")
    if not m:
        return None
    return {
        "reported_claim_count": int(m.group(1)),
        "reported_drawing_sheet_count": int(m.group(2)),
        "source_snippet": m.group(0),
        "span": {"start": m.start(), "end": m.end()},
    }


# =============================================================================
# Abstract extraction (text-only)
# =============================================================================

ABSTRACT_HEAD_PAT = re.compile(
    r"\(\s*57\s*\)\s*ABSTRACT\b|^\s*ABSTRACT\b",
    re.IGNORECASE | re.MULTILINE,
)


def extract_abstract(front_text: str) -> Dict[str, Any]:
    """
    Abstract starts at the END of heading match so "(57) ABSTRACT" is excluded.
    Ends at counts line if present, else end of page.
    """
    hm = ABSTRACT_HEAD_PAT.search(front_text or "")
    if not hm:
        return {"value": "", "span": None, "heading_span": None}

    abs_start = hm.end()
    abs_end = len(front_text)

    cm = REPORTED_COUNTS_PAT.search(front_text or "")
    if cm and cm.start() > hm.start():
        abs_end = cm.start()

    value = (front_text[abs_start:abs_end]).strip()
    return {
        "value": value,
        "span": {"start": abs_start, "end": abs_end},
        "heading_span": {"start": hm.start(), "end": hm.end()},
    }


# =============================================================================
# Title extraction robust to (56) intrusion
# =============================================================================

# Markers that definitely start a new metadata block and cannot be part of a title
TITLE_HARD_END_INID_PAT = re.compile(
    r"\(\s*(?:71|72|73|74|75|21|22|45|57)\s*\)",  # common INIDs after title
    re.IGNORECASE,
)

# Phrases that indicate the references/table area; title must not include these
TITLE_TABLE_STOP_PAT = re.compile(
    r"\b("
    r"U\.S\.\s*PATENT\s*DOCUMENTS|"
    r"FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS"
    r")\b",
    re.IGNORECASE,
)

# Remove only the interleaved (56) references label inside the title
INTERLEAVED_REFS_PAT = re.compile(r"\(\s*56\s*\)\s*References\s*Cited\b", re.IGNORECASE)
US_PATENT_DOCS_PAT = re.compile(
    r"\s*U\s*\.\s*S\s*\.\s*PATENT\s*DOCUMENTS", re.IGNORECASE
)
BARE_REFS_CITED_PAT = re.compile(r"\bReferences\s+Cited\b", re.IGNORECASE)

# If (71) is printed as "(71) Applicant:" on some docs, we want to stop at "(71)" regardless.
# If your stream sometimes loses parentheses, you can also stop on the word "Applicant:"
TITLE_APPLICANT_WORD_PAT = re.compile(r"\bApplicant\s*:", re.IGNORECASE)


def _find_span_end_after_54(front_text: str, start: int) -> int:
    """
    Initial broad window: prefer (75) then (57) then end-of-page.
    This window is not the final title; we will cut it down with internal stop rules.
    """
    candidates = []
    for pat in (
        re.compile(r"\(\s*75\s*\)", re.IGNORECASE),
        re.compile(r"\(\s*57\s*\)\s*ABSTRACT\b", re.IGNORECASE),
    ):
        m = pat.search(front_text, pos=start)
        if m:
            candidates.append(m.start())
    return min(candidates) if candidates else len(front_text)


def extract_title_between(front_text: str) -> Optional[Dict[str, Any]]:
    front_text = front_text or ""
    m54 = re.search(r"\(\s*54\s*\)", front_text)
    if not m54:
        return None

    start = m54.end()
    broad_end = _find_span_end_after_54(front_text, start)
    raw = front_text[start:broad_end]

    # 1) Delete interleaved "(56) References Cited" tokens inline (do NOT treat as a hard stop)
    raw = INTERLEAVED_REFS_PAT.sub(" ", raw)
    raw = BARE_REFS_CITED_PAT.sub(" ", raw)
    raw = US_PATENT_DOCS_PAT.sub(" ", raw)

    # 2) Now find the earliest hard stop inside the remaining span:
    #    - any later INID block start (71/72/73/74/75/21/22/45/57)
    #    - table headings like "U.S. PATENT DOCUMENTS"
    #    - "Applicant:" word (in case parentheses are mangled)
    stop_positions = []

    m_inid = TITLE_HARD_END_INID_PAT.search(raw)
    if m_inid:
        stop_positions.append(m_inid.start())

    m_tbl = TITLE_TABLE_STOP_PAT.search(raw)
    if m_tbl:
        stop_positions.append(m_tbl.start())

    m_app = TITLE_APPLICANT_WORD_PAT.search(raw)
    if m_app:
        stop_positions.append(m_app.start())

    if stop_positions:
        raw = raw[: min(stop_positions)]

    # 3) Remove any stray INID markers that remain (rare)
    raw = re.sub(r"\(\s*\d{2}\s*\)", " ", raw)

    cleaned = normalize_punctuation_spacing(normalize_whitespace_basic(raw))
    return {"value": cleaned or None, "span": {"start": start, "end": broad_end}}


# =============================================================================
# Assignee extraction (clean; no notice/disclaimer stored)
# =============================================================================

ASSIGNEE_HEADING_STOP_PAT = re.compile(
    r"\b("
    r"FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"U\.S\.\s*PATENT\s*DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS|"
    r"REFERENCES\s+CITED|"
    r"ABSTRACT|"
    r"Primary\s+Examiner|"
    r"Assistant\s+Examiner"
    r")\b",
    re.IGNORECASE,
)

ASSIGNEE_STOP_PAT = re.compile(
    r"(\(\*\)|\*|\bNotice\b\s*[:\-]|"
    r"\bSubject\s+to\s+any\s+disclaimer\b|"
    r"\bpatent\s+is\s+extended\s+or\s+adjusted\b)",
    re.IGNORECASE,
)

ASSIGNEE_FOREIGN_REF_STOP_PAT = re.compile(
    r"\b(EP|WO|PCT|KR|JP|CN|DE|FR|GB|CA|TW|RU|BR|IN|AU|IT|ES|NL|SE|CH)\b\s*[-A-Z0-9]",
    re.IGNORECASE,
)

ASSIGNEE_CONTINUED_PAT = re.compile(r"\bContinued\b|\(\s*Continued\s*\)", re.IGNORECASE)

COUNTRY_TAG_PAT = re.compile(r"\(\s*[A-Z]{2}\s*\)\s*$")  # (US) at end


def _cut_at_earliest(s: str, patterns: List[re.Pattern]) -> str:
    if not s:
        return s
    stops = []
    for pat in patterns:
        m = pat.search(s)
        if m:
            stops.append(m.start())
    return s[: min(stops)].strip() if stops else s.strip()


def extract_assignee_clean(inid_blocks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    raw = None
    span = None
    if "73" in inid_blocks:
        raw = inid_blocks["73"]["text"].strip()
        span = inid_blocks["73"]["span"]
    elif "71" in inid_blocks:
        raw = inid_blocks["71"]["text"].strip()
        span = inid_blocks["71"]["span"]
    else:
        return {"raw": None, "value": None, "span": None}

    raw2 = strip_leading_label(raw, ["Assignee", "Assignees", "Assignee:"])
    raw2 = normalize_punctuation_spacing(raw2).strip()

    # 1) Cut at headings / refs / boilerplate (this removes "FOREIGN PATENT DOCUMENTS")
    raw2 = _cut_at_earliest(
        raw2,
        [
            ASSIGNEE_HEADING_STOP_PAT,
            ASSIGNEE_FOREIGN_REF_STOP_PAT,
            ASSIGNEE_CONTINUED_PAT,
            ASSIGNEE_STOP_PAT,
        ],
    )

    # 2) Strip trailing country tag LAST
    raw2 = COUNTRY_TAG_PAT.sub("", raw2).strip()

    # 3) Final tidy
    raw2 = raw2.rstrip(" ,;.")

    return {"raw": raw, "value": raw2 or None, "span": span}


# =============================================================================
# Inventors parsing
# =============================================================================

INVENTOR_SPLIT_PAT = re.compile(r"\s*;\s*")
LOCATION_IN_PARENS_PAT = re.compile(r"\(([^)]+)\)\s*$")


def normalize_entity_name(name: str) -> str:
    n = normalize_punctuation_spacing(normalize_whitespace_basic(name))
    n = n.replace("’", "'").replace("–", "-").replace("—", "-")
    n = re.sub(r"[,\.;:\s]+$", "", n)
    return n


def split_name_and_location(raw: str) -> Dict[str, Optional[str]]:
    raw_clean = normalize_whitespace_basic(raw)
    m = LOCATION_IN_PARENS_PAT.search(raw_clean)
    if m:
        loc = normalize_punctuation_spacing(normalize_whitespace_basic(m.group(1)))
        nm = normalize_punctuation_spacing(raw_clean[: m.start()].strip())
    else:
        loc = None
        nm = normalize_punctuation_spacing(raw_clean)
    return {"name": nm or None, "location": loc}


def parse_inventors(raw_inventors_text: str) -> List[Dict[str, Optional[str]]]:
    raw_inventors_text = raw_inventors_text or ""
    chunks = [
        c.strip() for c in INVENTOR_SPLIT_PAT.split(raw_inventors_text) if c.strip()
    ]
    out: List[Dict[str, Optional[str]]] = []
    for c in chunks:
        parts = split_name_and_location(c)
        nm = parts["name"]
        out.append(
            {
                "raw": c,
                "name": nm,
                "location": parts["location"],
                "normalized_name": normalize_entity_name(nm) if nm else None,
            }
        )
    return out


# Add near other regexes
INVENTORS_TRAILING_HEADER_PAT = re.compile(
    r"\(\s*[A-Z]{2}\s*\)\s*Inventors?\s*:\s*$",  # "(US) Inventors:" at end
    re.IGNORECASE,
)

INVENTORS_EMBEDDED_HEADER_PAT = re.compile(
    r"\(\s*[A-Z]{2}\s*\)\s*Inventors?\s*:.*$",  # "(US) Inventors: ..." anywhere
    re.IGNORECASE,
)

INVENTORS_STRAY_LABEL_PAT = re.compile(
    r"\bInventors?\s*:\s*.*$",  # "Inventors:" label appearing mid-string
    re.IGNORECASE,
)


INVENTOR_HEADING_STOP_PAT = re.compile(
    r"\b("
    r"U\.S\.\s*PATENT\s*DOCUMENTS|"
    r"FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS|"
    r"REFERENCES\s+CITED|"
    r"ABSTRACT|"
    r"Primary\s+Examiner|"
    r"Assistant\s+Examiner"
    r")\b",
    re.IGNORECASE,
)

# Very characteristic of refs-table lines: "1/1999 Jordan, III et al."
REFS_DATE_LINE_PAT = re.compile(
    r"\b\d{1,2}\s*/\s*\d{4}\b",  # month/year
    re.IGNORECASE,
)

# Country tag immediately followed by a refs-date is a strong boundary:
# "(US) 1/1999 Jordan, III et al."
COUNTRY_TAG_THEN_REFS_DATE_PAT = re.compile(
    r"\(\s*[A-Z]{2}\s*\)\s*\d{1,2}\s*/\s*\d{4}\b",
    re.IGNORECASE,
)

COUNTRY_TAG_PAT = re.compile(r"\(\s*[A-Z]{2}\s*\)\s*$")


def extract_inventors(
    front_text: str, inid_blocks: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Inventors may appear under:
    - (72)
    - (75) Inventors:
    - or as label-based substring depending on extraction order.
    """
    if "72" in inid_blocks:
        raw = inid_blocks["72"]["text"].strip()
        span = inid_blocks["72"]["span"]
    elif "75" in inid_blocks:
        raw = inid_blocks["75"]["text"].strip()
        span = inid_blocks["75"]["span"]
    else:
        m = re.search(
            r"\bInventors?\s*[:\-]\s*(.+)", front_text or "", flags=re.IGNORECASE
        )
        if not m:
            return {"raw": None, "value": None, "span": None, "parsed": []}
        raw = m.group(1).strip()
        span = {"start": m.start(1), "end": m.end(1)}

    raw = strip_leading_label(raw, ["Inventors", "Inventor"])
    raw = raw.strip()

    # 1) Stop at obvious headings (best)
    m_h = INVENTOR_HEADING_STOP_PAT.search(raw)
    if m_h:
        raw = raw[: m_h.start()].strip()

    # 2) Stop at the very strong boundary "(US) 1/1999"
    m_bd = COUNTRY_TAG_THEN_REFS_DATE_PAT.search(raw)
    if m_bd:
        raw = raw[: m_bd.start()].strip()

    # 3) If we still see refs-like month/year dates, cut at the first one
    # (This is safe because inventor entries virtually never contain "1/1999".)
    m_d = REFS_DATE_LINE_PAT.search(raw)
    if m_d:
        raw = raw[: m_d.start()].strip()

    # 4) Finally strip a dangling country tag like "(US)"
    raw = COUNTRY_TAG_PAT.sub("", raw).strip()

    # 5) Existing removal of interleaved "Inventors:" headers if you already added it
    raw = INVENTORS_EMBEDDED_HEADER_PAT.sub("", raw).strip()
    raw = INVENTORS_STRAY_LABEL_PAT.sub("", raw).strip()
    raw = INVENTORS_TRAILING_HEADER_PAT.sub("", raw).strip()

    parsed = parse_inventors(raw)
    return {"raw": raw, "value": raw, "span": span, "parsed": parsed}


# =============================================================================
# Application number + filing date + grant date (INID + fallback regex)
# =============================================================================

# Fallback patterns (robust when INID blocks are disrupted)
APPL_NO_FALLBACK_PAT = re.compile(
    r"\bAppl\s*\.\s*No\s*\.\s*:\s*([0-9]{2}\s*/\s*[0-9\s*,\s*]{3,7}[0-9]{3})\b",
    re.IGNORECASE,
)
FILED_FALLBACK_PAT = re.compile(
    r"\bFiled\s*:\s*([A-Za-z\s*\.]+\s*+\d{1,2}\s*,\s*+\d{4})\b", re.IGNORECASE
)
DATE_OF_PATENT_FALLBACK_PAT = re.compile(
    r"\bDate\s+of\s+Patent\s*:\s*([A-Za-z\s*\.]+\s*+\d{1,2}\s*,\s*+\d{4})\b",
    re.IGNORECASE,
)
# Headings that frequently follow (21) and can contaminate the INID slice
APPL_STOP_PAT = re.compile(
    r"\b(OTHER\s+PUBLICATIONS|U\.S\.\s*PATENT\s*DOCUMENTS|FOREIGN\s+PATENT\s*DOCUMENTS|"
    r"REFERENCES\s+CITED|ABSTRACT|Primary\s+Examiner|Assistant\s+Examiner)\b",
    re.IGNORECASE,
)


def normalize_us_application_no(raw: str) -> Optional[str]:
    """
    Normalize variants like '13 / 766 , 598' -> '13/766,598'
    """
    if not raw:
        return None

    s = raw.upper()
    s = s.replace("O", "0")  # defensive; sometimes O->0 issues happen
    s = re.sub(r"\s+", "", s)

    # Keep only digits, slash, comma
    s = re.sub(r"[^0-9/,]", "", s)

    # Must contain exactly one slash with digits on both sides
    if s.count("/") != 1:
        return None
    left, right = s.split("/", 1)
    if not left.isdigit():
        return None

    # Remove commas from right side then reinsert properly if long enough
    right_digits = re.sub(r"[^0-9]", "", right)
    if not right_digits.isdigit():
        return None

    # Typical: 6 digits -> XXX,XXX ; sometimes 7+ exist; keep last 6 grouped
    if len(right_digits) >= 6:
        main = right_digits[:-3]
        tail = right_digits[-3:]
        return f"{left}/{main},{tail}"
    else:
        # Keep as-is (rare)
        return f"{left}/{right_digits}"


def extract_application_number(
    front_text: str, inid_blocks: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    raw = inid_blocks.get("21", {}).get("text")
    span = inid_blocks.get("21", {}).get("span")

    clean = strip_leading_label(
        normalize_punctuation_spacing(raw) or "",
        ["Appl. No.", "Appl No.", "Application No.", "Application No"],
    )
    clean = _cut_at_heading(clean, APPL_STOP_PAT) if clean else None

    # fallback if INID slice is broken
    if not clean:
        m = APPL_NO_FALLBACK_PAT.search(front_text or "")
        if m:
            clean = m.group(1).strip()
            clean = _cut_at_heading(clean, APPL_STOP_PAT)
            span = {"start": m.start(1), "end": m.end(1)}

    normalized = normalize_us_application_no(clean) if clean else None

    return {
        "raw": raw,
        "value": normalized or clean,
        "normalized": normalized,
        "span": span,
    }


def extract_filed_date(
    front_text: str, inid_blocks: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    raw = inid_blocks.get("22", {}).get("text")
    span = inid_blocks.get("22", {}).get("span")
    clean = strip_leading_label(raw or "", ["Filed"])
    clean = clean or None

    iso = parse_uspto_date_to_iso(clean) if clean else None

    # fallback
    if not iso:
        m = FILED_FALLBACK_PAT.search(front_text or "")
        if m:
            clean = m.group(1).strip()
            span = {"start": m.start(1), "end": m.end(1)}
            iso = parse_uspto_date_to_iso(clean) if clean else None

    return {"raw": raw, "value": clean, "iso": iso, "span": span}


def extract_grant_date(
    front_text: str, inid_blocks: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    raw = inid_blocks.get("45", {}).get("text")
    span = inid_blocks.get("45", {}).get("span")

    if raw:
        clean = strip_leading_label(
            raw, ["Date of Patent", "Date of Patent:", "Date of Patent :"]
        )
        clean = clean or None
        iso = parse_uspto_date_to_iso(clean) if clean else None
        if iso:
            return {"raw": raw, "value": clean, "iso": iso, "span": span}

    # fallback to explicit "Date of Patent:" text
    m = DATE_OF_PATENT_FALLBACK_PAT.search(front_text or "")
    if m:
        clean = m.group(1).strip()
        iso = parse_uspto_date_to_iso(clean) if clean else None
        return {"raw": raw, "value": clean, "iso": iso, "span": span}

    # fallback to first date in the front text
    DATE_GENERIC_PAT = re.compile(r"\b([A-Za-z\.]+\s+\d{1,2},\s+\d{4})\b")
    m = DATE_GENERIC_PAT.search(front_text or "")
    if not m:
        raise TypeError("No grant date found")
        return {"raw": None, "value": None, "iso": None, "span": None}

    clean = m.group(1).strip()
    iso = parse_uspto_date_to_iso(clean) if clean else None

    return {
        "raw": m.group(0),
        "value": clean or None,
        "iso": iso,
        "span": {"start": m.start(0), "end": m.end(0)},
    }


# =============================================================================
# Get the prior publication number
# =============================================================================


PRIOR_PUB_HEAD_PAT = re.compile(r"\bPrior\s+Publication\s+Data\b", re.IGNORECASE)

# Matches: "US 2016/0238378 A1" and variants with weird slashes
US_PRIOR_PUB_PAT = re.compile(
    r"\bUS\s+((?:19|20)\d{2})\s*[/\.\u2044\u2215\uFF0F]\s*([0-9O][0-9O,\s\.]{5,12})\s*(A\d|A9|B\d)\b",
    re.IGNORECASE,
)


def extract_prior_publications(page0_text: str) -> List[Dict[str, str]]:
    """
    Extract the patent's own prior publication numbers from the 'Prior Publication Data' region.
    Returns a list of dicts: {canonical, display, kind}.
    """
    t = normalize_separators_for_refs(page0_text or "")

    # Try to restrict to the region after the heading if it exists
    mh = PRIOR_PUB_HEAD_PAT.search(t)
    region = t[mh.start() :] if mh else t

    out: List[Dict[str, str]] = []
    seen = set()

    for m in US_PRIOR_PUB_PAT.finditer(region):
        year = m.group(1)
        serial_raw = m.group(2)
        kind = (m.group(3) or "").upper()

        canon = normalize_us_pub_app(year, serial_raw)
        if not canon:
            continue
        if canon in seen:
            continue
        seen.add(canon)

        out.append(
            {
                "canonical": canon,  # e.g. 20160238378
                "display": f"{year}/{canon[4:]}",  # e.g. 2016/0238378
                "kind": kind,  # e.g. A1
            }
        )
    return out


# =============================================================================
# References cited extraction (region-based; supports continuation to page 2+)
# =============================================================================

REFS_START_PAT = re.compile(r"\(\s*56\s*\)\s*References\s+Cited\b", re.IGNORECASE)
REFS_CONTINUED_PAT = re.compile(r"\(\s*Continued\s*\)|\bContinued\b", re.IGNORECASE)

# Strict grouped patent number: avoids capturing classification codes.
US_PATENT_GROUPED_PAT = re.compile(r"\b(\d{1,2})\s*[,\.]\s*(\d{3})\s*[,\.]\s*(\d{3})\b")

# Matches things like:
#   2001/0043333 A1
#   2003. O165178 A1
#   2004/O112863 A1
#   2007/0293,052 A1
US_PUB_APP_PAT = re.compile(
    r"""
    \b((?:19|20)\d{2})                         # year
    \s*[/\.\u2044\u2215\uFF0F]\s*              # separator: / or . or unicode slashes
    ([0-9O][0-9O,\s\.]{5,12})                  # serial-ish (may contain commas/spaces/dots; may have O)
    \s*
    (A\d|A9|B\d)                               # kind code REQUIRED
    \s*[*†]?                                   # optional star/dagger
    (?=                                       # IMPORTANT: allow immediate date run-in or whitespace/end
        \s|$|[^\w]|
        \d{1,2}\s*[/\.\u2044\u2215\uFF0F]\s*(?:19|20)\d{2}   # e.g., 4/2009
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def normalize_us_pub_app(year: str, serial_raw: str) -> Optional[str]:
    """
    Normalize US published application number:
      year="2001", serial_raw="0043333" -> "20010043333"
      year="2003", serial_raw="O165178" -> "20030165178"  (O -> 0)
      year="2007", serial_raw="0293,052" -> "20070293052"
    Returns a digits-only canonical string: YYYY + 7 digits (usually).
    """
    if not year or not serial_raw:
        return None

    s = serial_raw.upper()

    # Replace letter O with zero when it's in a digit-ish context
    s = s.replace("O", "0")

    # Drop commas/spaces
    s = re.sub(r"[,\s]+", "", s)

    # Keep digits only
    s = re.sub(r"\D", "", s)

    # Typical US pub serial is 7 digits; sometimes extraction yields 6–8 due to noise
    if len(s) < 6 or len(s) > 8:
        return None

    # Pad left with zeros to 7 digits when short
    if len(s) < 7:
        s = s.zfill(7)

    return f"{year}{s}"


def normalize_separators_for_refs(text: str) -> str:
    """
    Normalize common Unicode slash variants to ASCII '/' so regexes match.
    """
    if not text:
        return ""
    return (
        text.replace("\u2044", "/")  # FRACTION SLASH (⁄)
        .replace("\u2215", "/")  # DIVISION SLASH (∕)
        .replace("\uff0f", "/")  # FULLWIDTH SOLIDUS (／)
    )


def _slice_refs_from_one_page(page_text: str) -> Optional[str]:
    """
    Slice from after (56) References Cited to (57) ABSTRACT if it appears on the same page, else to end.
    """
    t = page_text or ""
    m = REFS_START_PAT.search(t)
    if not m:
        return None
    start = m.end()
    end = len(t)
    m_abs = ABSTRACT_HEAD_PAT.search(t)
    if m_abs and m_abs.start() > start:
        end = m_abs.start()
    return t[start:end].strip()


def _page_contains_reference_table_like_content(t: str) -> bool:
    """
    Conservative signal for continued references pages.
    """
    if not t:
        return False
    # headings seen in ref tables
    if re.search(r"\bU\.S\.\s*PATENT\s*DOCUMENTS\b", t, re.IGNORECASE):
        return True
    if re.search(r"\bFOREIGN\s+PATENT\s+DOCUMENTS\b", t, re.IGNORECASE):
        return True
    if re.search(r"\bOTHER\s+PUBLICATIONS\b", t, re.IGNORECASE):
        return True
    # continuation marker
    if REFS_CONTINUED_PAT.search(t):
        return True
    return False


def normalize_kindcode_date_runins(text: str) -> str:
    """
    Fix common run-in where kind code touches the following date:
      'A14/2009'  -> 'A1 4/2009'
      'A112/2010' -> 'A1 12/2010'
      'B21/2008'  -> 'B2 1/2008'
    """
    if not text:
        return ""
    # Kind code (A1/A9/B1/B2 etc.) immediately followed by day/month number then '/' or '.'
    return re.sub(
        r"\b((?:A\d|A9|B\d))(\d{1,2})\s*([/\.\u2044\u2215\uFF0F])\s*((?:19|20)\d{2})\b",
        r"\1 \2/\4",
        text,
        flags=re.IGNORECASE,
    )


REFS_START_PAT = re.compile(r"\(\s*56\s*\)\s*References\s+Cited", re.IGNORECASE)
ABSTRACT_PAT = re.compile(r"\(\s*57\s*\)\s*ABSTRACT", re.IGNORECASE)

REFS_EVIDENCE_PAT = re.compile(
    r"\b(U\.S\.\s*PATENT\s*DOCUMENTS|FOREIGN\s+PATENT\s+DOCUMENTS|OTHER\s+PUBLICATIONS|\(\s*56\s*\)\s*References\s+Cited)\b",
    re.IGNORECASE,
)

# Evidence patterns that indicate the page contains citation rows even if headings are missing
US_GRANT_EVIDENCE_PAT = re.compile(r"\b\d{1,2}\s*[,\.]\s*\d{3}\s*[,\.]\s*\d{3}\b")
US_PUB_EVIDENCE_PAT = re.compile(
    r"\b(?:19|20)\d{2}\s*[/\.\u2044\u2215\uFF0F]\s*[0-9O][0-9O,\s\.]{5,12}\s*A\d",
    re.IGNORECASE,
)


RELATED_APP_HEAD_PAT = re.compile(
    r"\bRelated\s+U\.S\.\s+Application\s+Data\b", re.IGNORECASE
)
PRIMARY_EXAMINER_PAT = re.compile(r"\bPrimary\s+Examiner\b", re.IGNORECASE)


# More tolerant: allow newlines and weird spacing between tokens
REFS_START_PAT = re.compile(r"\(\s*56\s*\)\s*References\s*Cited", re.IGNORECASE)
REFS_WORDS_PAT = re.compile(r"\bReferences\s*Cited\b", re.IGNORECASE)

US_PAT_DOCS_PAT = re.compile(r"\bU\.S\.\s*PATENT\s*DOCUMENTS\b", re.IGNORECASE)
FOREIGN_PAT_DOCS_PAT = re.compile(r"\bFOREIGN\s+PATENT\s+DOCUMENTS\b", re.IGNORECASE)
OTHER_PUBS_PAT = re.compile(r"\bOTHER\s+PUBLICATIONS\b", re.IGNORECASE)

ABSTRACT_PAT = re.compile(r"\(\s*57\s*\)\s*ABSTRACT\b", re.IGNORECASE)

# Evidence for continuation pages
REFS_EVIDENCE_PAT = re.compile(
    r"\b(U\.S\.\s*PATENT\s*DOCUMENTS|FOREIGN\s+PATENT\s+DOCUMENTS|OTHER\s+PUBLICATIONS|\(\s*56\s*\)\s*References\s+Cited|References\s+Cited)\b",
    re.IGNORECASE,
)
US_GRANT_EVIDENCE_PAT = re.compile(
    r"\b\d{1,2}\s*[,\.]\s*\d{3}\s*[,\.]\s*\d{3}\b"
)  # e.g., 5,864,394
US_PUB_EVIDENCE_PAT = re.compile(
    r"\b(?:19|20)\d{2}\s*[/\.\u2044\u2215\uFF0F]\s*[0-9O][0-9O,\s\.]{5,12}\s*A\d",
    re.IGNORECASE,
)

RELATED_APP_HEAD_PAT = re.compile(
    r"\bRelated\s+U\.S\.\s+Application\s+Data\b", re.IGNORECASE
)

# These are reasonable “end of related-app block” anchors on front-matter pages
RELATED_APP_END_PAT = re.compile(
    r"\b("
    r"\(\s*56\s*\)\s*References\s+Cited|"
    r"References\s+Cited|"
    r"U\.S\.\s*PATENT\s*DOCUMENTS|"
    r"FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS|"
    r"Primary\s+Examiner|"
    r"\(\s*57\s*\)\s*ABSTRACT"
    r")\b",
    re.IGNORECASE,
)


def strip_related_application_data_block(text: str) -> str:
    """
    Remove the 'Related U.S. Application Data' paragraph(s) only.
    Keep the remainder of the page because (56) tables may appear later.
    """
    if not text:
        return ""
    m = RELATED_APP_HEAD_PAT.search(text)
    if not m:
        return text

    start = m.start()
    m_end = RELATED_APP_END_PAT.search(text, m.end())
    if not m_end:
        # If we cannot find a safe end marker, remove just a bounded chunk (failsafe)
        # up to 1200 chars to avoid nuking the entire page.
        end = min(len(text), m.end() + 1200)
        return (text[:start] + "\n" + text[end:]).strip()

    end = m_end.start()
    return (text[:start] + "\n" + text[end:]).strip()


FOREIGN_PREFIXES = (
    "WO",
    "WIPO",
    "EP",
    "EPO",
    "PCT",
    "KR",
    "JP",
    "CN",
    "DE",
    "FR",
    "GB",
    "UK",
    "CA",
    "TW",
    "RU",
    "BR",
    "IN",
    "AU",
    "IT",
    "ES",
    "NL",
    "SE",
    "CH",
)

# Characters we consider “glue” between a prefix and the number
_GLUE = r"[\s\(\)\[\]\{\}:;,\.\-–—/]*"

# Matches e.g. "WO ", "WO-", "(WO)", "EP", "EP-" directly before the year
FOREIGN_PREFIX_BEFORE_YEAR_PAT = re.compile(
    rf"(?:^|[\s\(\[\{{])"
    rf"({'|'.join(map(re.escape, FOREIGN_PREFIXES))})"
    rf"{_GLUE}$",
    re.IGNORECASE,
)


def is_foreign_publication_context(text: str, match_start: int) -> bool:
    """
    Returns True if the publication-like token at match_start appears to be preceded
    by a foreign authority prefix (WO/EP/KR/JP/...).

    We look at a short window immediately before the match and see if it ends with
    a known foreign prefix plus glue punctuation.
    """
    # Look back far enough to include "(WO) " and similar
    window_start = max(0, match_start - 20)
    prefix_window = text[window_start:match_start].upper()

    # Normalize whitespace for reliable matching
    prefix_window = re.sub(r"\s+", " ", prefix_window)

    return bool(FOREIGN_PREFIX_BEFORE_YEAR_PAT.search(prefix_window))


def _page0_refs_start(p0: str) -> int | None:
    """
    Page-0 references can be interleaved into (54). Find the earliest usable anchor.
    """
    candidates = []
    for pat in (
        REFS_START_PAT,
        REFS_WORDS_PAT,
        US_PAT_DOCS_PAT,
        FOREIGN_PAT_DOCS_PAT,
        OTHER_PUBS_PAT,
    ):
        m = pat.search(p0)
        if m:
            candidates.append(m.start())
    return min(candidates) if candidates else None


def extract_references_region(
    pages_text: List[str], *, max_pages: int = 3
) -> Dict[str, Any]:
    if not pages_text:
        return {"raw": "", "pages_used": []}

    limit = min(len(pages_text), max_pages)
    pages_used: List[int] = []
    chunks: List[str] = []

    # --- Page 0: strict slice ---
    p0 = pages_text[0] or ""
    start0 = _page0_refs_start(p0)
    if start0 is None:
        return {"raw": "", "pages_used": []}

    end0 = len(p0)
    m_abs = ABSTRACT_PAT.search(p0)
    if m_abs and m_abs.start() > start0:
        end0 = m_abs.start()

    chunks.append(p0[start0:end0].strip())
    pages_used.append(0)

    # --- Continuation pages: include if refs evidence, but strip Related App Data contamination ---
    for i in range(1, limit):
        pi = pages_text[i] or ""
        if not pi.strip():
            continue

        pi2 = strip_related_application_data_block(pi)

        has_heading = bool(REFS_EVIDENCE_PAT.search(pi2))
        has_numbers = bool(
            US_GRANT_EVIDENCE_PAT.search(pi2) or US_PUB_EVIDENCE_PAT.search(pi2)
        )

        if has_heading or has_numbers:
            chunks.append(pi2.strip())
            pages_used.append(i)

    return {"raw": "\n\n".join(chunks).strip(), "pages_used": pages_used}


def extract_us_publications_from_refs(
    refs_text: str, *, exclude_canonicals: Optional[set] = None
) -> List[Dict[str, str]]:
    exclude_canonicals = exclude_canonicals or set()
    out = []
    seen = set()

    t = normalize_separators_for_refs(refs_text)
    t = normalize_kindcode_date_runins(t)
    t = re.sub("Al", "A1", t)  # common OCR error

    for m in US_PUB_APP_PAT.finditer(t):
        if is_foreign_publication_context(t, m.start()):
            continue
        year = m.group(1)
        serial_raw = m.group(2)
        kind = (m.group(3) or "").upper()

        canon = normalize_us_pub_app(year, serial_raw)
        if not canon:
            continue

        if canon in exclude_canonicals or canon in seen:
            continue
        seen.add(canon)

        out.append(
            {
                "canonical": canon,
                "display": f"{year}/{canon[4:]}",
                "kind": kind,
                "source_match": m.group(0),  # REMOVE after debugging
            }
        )

    out.sort(key=lambda x: int(x["canonical"]))

    return out


def extract_cited_us_patents_from_refs(
    refs_text: str, own_patent_digits: Optional[str]
) -> List[Dict[str, str]]:
    """
    Extract cited US patent numbers from references region (strict grouped forms only).
    Excludes the patent's own number.
    """
    seen = set()
    out: List[Dict[str, str]] = []
    for m in US_PATENT_GROUPED_PAT.finditer(refs_text or ""):
        digits = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        if own_patent_digits and digits == own_patent_digits:
            continue
        if digits in seen:
            continue
        seen.add(digits)
        out.append(
            {
                "digits": digits,
                "display": comma_format_us_patent(digits),
                "source_match": m.group(0),
            }
        )

    out.sort(key=lambda x: int(x["digits"]))
    return out


# =============================================================================
# Main entry points
# =============================================================================


def parse_front_page(front_text: str) -> Dict[str, Any]:
    """
    Parse a cleaned page-0 text string only.
    References are extracted only from page-0 (56) region; for continued references use parse_front_matter().
    """
    front_text = front_text or ""
    inid = parse_inid_blocks(front_text)

    qa_warnings: List[str] = []
    qa_info: Dict[str, Any] = {}

    # Patent header
    patent_header = None
    patent_header_span = None
    mh = PATENT_HEADER_PAT.search(front_text)
    if mh:
        patent_header = mh.group(0)
        patent_header_span = {"start": mh.start(), "end": mh.end()}
    else:
        qa_warnings.append("missing_patent_header_number")

    patent_digits = normalize_patent_number_digits(patent_header or "")
    patent_normalized = (
        normalize_us_patent_header(patent_header or "") if patent_header else None
    )
    kind_code = None
    if patent_header:
        mk = KIND_CODE_PAT.search(patent_header)
        kind_code = mk.group(1) if mk else None

    if patent_header and not patent_digits:
        qa_warnings.append("patent_number_digits_not_found")

    # Title
    title_obj = extract_title_between(front_text)
    if not title_obj or not title_obj.get("value"):
        qa_warnings.append("missing_title")

    # Assignee
    assignee_obj = extract_assignee_clean(inid)
    if not assignee_obj.get("value"):
        qa_warnings.append("missing_assignee")

    # Inventors
    inventors_obj = extract_inventors(front_text, inid)
    if not inventors_obj.get("parsed"):
        qa_warnings.append("missing_inventors")

    # Application/Filed/Grant (with fallbacks)
    appl_obj = extract_application_number(front_text, inid)
    if not appl_obj.get("value"):
        qa_warnings.append("missing_or_empty_application_number")
    if appl_obj.get("value") and APPL_STOP_PAT.search(appl_obj.get("raw") or ""):
        qa_info["application_no_was_trimmed_at_heading"] = True

    filed_obj = extract_filed_date(front_text, inid)
    if filed_obj.get("value") and not filed_obj.get("iso"):
        qa_warnings.append("filed_date_unparsed")
    if not filed_obj.get("value"):
        qa_warnings.append("missing_filed_date")

    grant_obj = extract_grant_date(front_text, inid)
    if grant_obj.get("value") and not grant_obj.get("iso"):
        qa_warnings.append("grant_date_unparsed")
    if not grant_obj.get("value"):
        qa_warnings.append("missing_grant_date")

    # Counts
    counts_obj = extract_reported_counts(front_text)
    if not counts_obj:
        qa_warnings.append("missing_reported_counts")

    # Abstract
    abstract_obj = extract_abstract(front_text)
    if not abstract_obj.get("value"):
        qa_warnings.append("missing_abstract")

    # Front matter span: before abstract heading if present
    if abstract_obj.get("heading_span"):
        fm_span = {"start": 0, "end": abstract_obj["heading_span"]["start"]}
        front_matter = front_text[: fm_span["end"]].strip()
    else:
        fm_span = {"start": 0, "end": len(front_text)}
        front_matter = front_text.strip()

    prior_pubs = extract_prior_publications(front_text)

    # References region only from page 0 (best effort)
    refs_region = extract_references_region([front_text], max_pages=1)
    refs_text = refs_region["raw"]
    cited_grants = extract_cited_us_patents_from_refs(
        refs_text, patent_digits
    )  # your existing one
    cited_pubs = extract_us_publications_from_refs(
        refs_text, exclude_canonicals={p["canonical"] for p in prior_pubs}
    )

    if REFS_START_PAT.search(front_text) and not cited_grants:
        qa_warnings.append("no_cited_us_patents_found")
    if REFS_START_PAT.search(front_text) and not cited_pubs:
        qa_warnings.append("no_cited_us_publications_found")

    # QA info
    qa_info["inid_codes_found"] = sorted(list(inid.keys()))
    qa_info["inventor_count"] = len(inventors_obj.get("parsed") or [])
    qa_info["cited_us_patent_count"] = len(cited_grants)
    qa_info["cited_us_publication_count"] = len(cited_pubs)
    qa_info["references_pages_used"] = refs_region.get("pages_used", [])

    if counts_obj:
        qa_info["reported_claim_count"] = counts_obj.get("reported_claim_count")
        qa_info["reported_drawing_sheet_count"] = counts_obj.get(
            "reported_drawing_sheet_count"
        )

    return {
        "raw_text": front_text,
        "inid_blocks": inid,
        "qa": {"warnings": qa_warnings, "info": qa_info},
        "front_matter": front_matter,
        "front_matter_span": fm_span,
        "patent_number": {
            "raw": patent_header,
            "span": patent_header_span,
            "digits": patent_digits,
            "normalized": patent_normalized,
            "kind_code": kind_code,
        },
        "title": title_obj or {"value": None, "span": None},
        "assignee": assignee_obj,
        "inventors": inventors_obj,
        "application_no": appl_obj,
        "filed": filed_obj,
        "grant_date": grant_obj,
        "reported_counts": counts_obj,
        "abstract": abstract_obj,
        "prior_publication_data": {"us_publications": prior_pubs},
        "references_cited": {
            "raw": refs_region["raw"],
            "pages_used": refs_region.get("pages_used", []),
            "cited_us_patents": cited_grants,
            "cited_us_publications": cited_pubs,  # published apps (canonical)
        },
    }


def parse_front_matter(pages_text: List[str], *, max_pages: int = 3) -> Dict[str, Any]:
    """
    Parse front matter using multiple pages (page 0 + possible continuation pages).

    This function is the correct entry point for patents where:
      - (56) References Cited continues onto page 2+,
      - "Prior Publication Data" on page 0 would otherwise contaminate references,
      - front-page INID slicing is disrupted by column interleaving.

    Behavior:
      - Metadata fields are parsed from page 0 text (as usual).
      - References are extracted strictly from the (56) region across pages 0..max_pages-1.
      - Returns the same schema as parse_front_page(), but with multi-page references.
    """
    if not pages_text:
        return parse_front_page("")

    result = pages_text.parse()
    raise TypeError("pages_text must be a list of strings")

    # Limit pages scanned for front matter
    limit = min(len(pages_text), max_pages)
    pages_text = pages_text[:limit]

    # 1) Parse base metadata from page 0
    page0 = pages_text[0] or ""
    base = parse_front_page(page0)

    # 2) Extract multi-page references region (starting at (56), include continuation pages)
    refs_region = extract_references_region(pages_text, max_pages=limit)
    refs_text = refs_region.get("raw", "") or ""

    # 3) Extract citations from references region
    own_patent_digits = (base.get("patent_number") or {}).get("digits")

    cited_grants = extract_cited_us_patents_from_refs(refs_text, own_patent_digits)

    # Published applications (A1/A9/etc.) with OCR artifacts (O->0, dot vs slash, commas/spaces)
    # NOTE: This function must exist in your module; if you haven't added it yet,
    # add the implementation we discussed (US_PUB_APP_PAT + normalize_us_pub_app).
    prior = (base.get("prior_publication_data") or {}).get("us_publications") or []
    exclude = {p["canonical"] for p in prior if p.get("canonical")}
    cited_pubs = extract_us_publications_from_refs(
        refs_text, exclude_canonicals=exclude
    )

    # 4) Replace references section in base output
    base["references_cited"] = {
        "raw": refs_text,
        "pages_used": refs_region.get("pages_used", []),
        "cited_us_patents": cited_grants,
        "cited_us_publications": cited_pubs,
    }

    # 5) QA update (remove page0-only warning, re-evaluate with multi-page refs)
    qa = base.get("qa") or {"warnings": [], "info": {}}
    warnings = list(qa.get("warnings") or [])
    info = dict(qa.get("info") or {})

    # Update counts
    info["references_pages_used"] = refs_region.get("pages_used", [])
    info["cited_us_patent_count"] = len(cited_grants)
    info["cited_us_publication_count"] = len(cited_pubs)

    # Remove any prior no-cited warning computed from page0-only parsing
    warnings = [w for w in warnings if w != "no_cited_us_patents_found"]
    warnings = [w for w in warnings if w != "no_cited_us_publications_found"]

    # Re-add warning only if (56) exists on page0 but still nothing extracted across pages
    if REFS_START_PAT.search(page0) and (
        len(cited_grants) == 0 and len(cited_pubs) == 0
    ):
        warnings.append("no_cited_us_patents_found")

    base["qa"] = {"warnings": warnings, "info": info}
    return base


def canonical_front_page(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produce a stable, test-friendly projection of parse_front_page()/parse_front_matter() output.
    """
    pn = (parsed.get("patent_number") or {}).get("normalized")

    inventors = []
    inv_parsed = (parsed.get("inventors") or {}).get("parsed") or []
    for inv in inv_parsed:
        nm = inv.get("name") or inv.get("raw")
        if nm:
            inventors.append(normalize_whitespace_basic(nm))

    cited = (parsed.get("references_cited") or {}).get("cited_us_patents") or []
    cited_digits = [c["digits"] for c in cited if c.get("digits")]

    pubs = (parsed.get("references_cited") or {}).get("cited_us_publications") or []
    pubs_canon = [p["canonical"] for p in pubs if p.get("canonical")]

    counts = parsed.get("reported_counts") or {}

    return {
        "patent_number_normalized": pn,
        "title": (parsed.get("title") or {}).get("value"),
        "assignee": (parsed.get("assignee") or {}).get("value"),
        "inventors": inventors,
        "application_no": (parsed.get("application_no") or {}).get("value"),
        "filed_iso": (parsed.get("filed") or {}).get("iso"),
        "grant_iso": (parsed.get("grant_date") or {}).get("iso"),
        "reported_claim_count": counts.get("reported_claim_count"),
        "reported_drawing_sheet_count": counts.get("reported_drawing_sheet_count"),
        "cited_us_patents_digits": cited_digits,
        "cited_us_publications": pubs_canon,
    }


# =============================================================================
# Optional CLI smoke-test
# =============================================================================

if __name__ == "__main__":
    import sys

    try:
        from pypdf import PdfReader
    except Exception:
        print("pypdf is required. Install with: pip install pypdf")
        raise

    if len(sys.argv) < 2:
        print("Usage: python parse_front_page.py <pdf_path> [--pages N]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    max_pages = 2
    if "--pages" in sys.argv:
        idx = sys.argv.index("--pages")
        if idx + 1 < len(sys.argv):
            max_pages = int(sys.argv[idx + 1])

    reader = PdfReader(pdf_path)
    pages = [
        extract_page_text(reader, i, is_front_page=(i == 0))
        for i in range(min(max_pages, len(reader.pages)))
    ]

    parsed = parse_front_matter(pages, max_pages=max_pages)
    canon = canonical_front_page(parsed)

    print("Patent:", canon["patent_number_normalized"])
    print("Title:", canon["title"])
    print("Assignee:", canon["assignee"])
    print("Inventors:", canon["inventors"])
    print("Appl:", canon["application_no"])
    print("Filed ISO:", canon["filed_iso"])
    print("Grant ISO:", canon["grant_iso"])
    print(
        "Counts:",
        canon["reported_claim_count"],
        "claims;",
        canon["reported_drawing_sheet_count"],
        "drawing sheets",
    )
    print("Cited US patents:", len(canon["cited_us_patents_digits"]))
    print("Cited US publications:", len(canon["cited_us_publications"]))
    print("QA warnings:", parsed.get("qa", {}).get("warnings"))
