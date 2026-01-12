from datetime import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

PATENT_HEADER_PAT = re.compile(r"\bUS\s+[\d,\s]{7,15}\s+B\d\b")
KIND_CODE_PAT = re.compile(r"\bB\d\b")


# -----------------------------
# Label stripping (front page)
# -----------------------------
def strip_leading_label(text: str, labels: List[str]) -> str:
    """
    Removes one of the provided labels from the beginning of a string, if present.
    Example: "Appl. No.: 12/345,678" -> "12/345,678"
    """
    t = (text or "").strip()
    for lab in labels:
        # allow optional punctuation after label
        pat = re.compile(rf"^\s*{re.escape(lab)}\s*[:\-]?\s*", re.IGNORECASE)
        if pat.search(t):
            return pat.sub("", t).strip()
    return t


def normalize_patent_number_digits(s: str) -> Optional[str]:
    """
    Extracts digit-only patent number from strings like:
      "US 7,629,993 B2" -> "7629993"
    Returns None if no 7-8 digit run found.
    """
    if not s:
        return None
    # first prefer explicit comma-style
    m = re.search(r"\b(\d{1,2}),(\d{3}),(\d{3})\b", s)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    # fallback: 7-8 consecutive digits
    m = re.search(r"\b(\d{7,8})\b", s)
    return m.group(1) if m else None


def comma_format_us_patent(digits: str) -> str:
    """
    7629993 -> 7,629,993
    """
    if not digits or not digits.isdigit():
        return digits
    n = int(digits)
    return f"{n:,}"


# -----------------------------
# Date parsing
# -----------------------------
MONTH_FIX = {
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


def parse_uspto_date_to_iso(raw: str) -> Optional[str]:
    """
    Accepts strings like:
      "Dec. 8, 2009"
      "December 8, 2009"
    Returns ISO date "2009-12-08" or None.
    """
    if not raw:
        return None
    s = re.sub(r"\s+", " ", raw.strip())
    # normalize abbreviated months with trailing dot
    for k, v in MONTH_FIX.items():
        s = s.replace(k, v)

    # Try common formats
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.date().isoformat()
        except ValueError:
            pass
    return None


INID_ANY_PAT = re.compile(r"\(\s*(\d{2})\s*\)")

REF_CITED_LABEL_PAT = re.compile(r"\(\s*56\s*\)\s*References\s+Cited", re.IGNORECASE)


def extract_title_between(front_text: str) -> Optional[Dict[str, Any]]:
    m54 = re.search(r"\(\s*54\s*\)", front_text)
    if not m54:
        return None

    # Prefer (75) as end anchor (works for your PDF); otherwise fall back to next INID marker.
    m75 = re.search(r"\(\s*75\s*\)", front_text)
    if m75:
        end = m75.start()
    else:
        # fallback: next INID marker after (54)
        mnext = INID_ANY_PAT.search(front_text, pos=m54.end())
        end = mnext.start() if mnext else len(front_text)

    raw_span_text = front_text[m54.end() : end]

    # Remove only the "(56) References Cited" label if it appears inside
    cleaned = REF_CITED_LABEL_PAT.sub("", raw_span_text)

    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip() or None

    return {
        "value": cleaned,
        "span": {"start": m54.end(), "end": end},
    }


US_PATENT_NUM_ANY_PAT = re.compile(r"\b(\d{1,2},\d{3},\d{3}|\d{7,8})\b")


def extract_cited_us_patents_anywhere(text: str) -> List[Dict[str, str]]:
    """
    Extracts US patent numbers from text as:
      - comma-formatted: 7,629,993
      - digits only: 7629993
    Returns list of dicts with digits + display (comma formatted).
    De-duplicates by digits preserving order.
    """
    seen = set()
    out: List[Dict[str, str]] = []
    for m in US_PATENT_NUM_ANY_PAT.finditer(text or ""):
        token = m.group(1)
        digits = normalize_patent_number_digits(token)
        if not digits:
            continue
        if digits in seen:
            continue
        seen.add(digits)
        out.append({"digits": digits, "display": comma_format_us_patent(digits)})
    return out


INID_MARKER_PAT = re.compile(r"\(\s*(\d{2})\s*\)")  # e.g. "(54)"


def parse_inid_blocks(front_text: str) -> Dict[str, Dict[str, Any]]:
    """
    Returns dict: code -> { "text": str, "span": {"start": int, "end": int} }
    Spans are [start, end) in front_text.
    """
    matches = list(INID_MARKER_PAT.finditer(front_text))
    blocks: Dict[str, Dict[str, Any]] = {}

    for i, m in enumerate(matches):
        code = m.group(1)  # "54"
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(front_text)
        value = front_text[start:end].strip()

        # Keep first occurrence if repeated; many patents repeat some codes in odd ways
        if code not in blocks and value:
            blocks[code] = {"text": value, "span": {"start": start, "end": end}}

    return blocks


# -----------------------------
# Assignee notice splitting
# -----------------------------
NOTICE_SPLIT_PAT = re.compile(r"\bNotice\b\s*[:\-]", re.IGNORECASE)


def split_assignee_and_notice(raw_assignee_block: str) -> Tuple[str, Optional[str]]:
    """
    Splits assignee block into assignee vs notice if a 'Notice:' marker appears.
    """
    t = (raw_assignee_block or "").strip()
    m = NOTICE_SPLIT_PAT.search(t)
    if not m:
        return t, None
    assignee_part = t[: m.start()].strip()
    notice_part = t[m.start() :].strip()
    # strip the leading "Notice:" label for the notice text
    notice_part = strip_leading_label(notice_part, ["Notice"])
    return assignee_part, notice_part


# Common patterns: "Lastname; Firstname (City, ST)" OR "Firstname Lastname (City, ST)"
# USPTO grant PDFs often separate multiple inventors by semicolons.
INVENTOR_SPLIT_PAT = re.compile(r"\s*;\s*")

LOCATION_IN_PARENS_PAT = re.compile(r"\(([^)]+)\)\s*$")  # trailing "(City, ST)" or "(Country)"


def normalize_whitespace_basic(s: str) -> str:
    s = s or ""
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_entity_name(name: str) -> str:
    """
    Lightweight normalization for matching/search:
    - collapse whitespace
    - strip trailing punctuation
    - normalize common unicode apostrophes/dashes
    """
    n = normalize_whitespace_basic(name)
    n = n.replace("’", "'").replace("–", "-").replace("—", "-")
    n = re.sub(r"[,\.;:\s]+$", "", n)  # trailing punctuation/space
    return n


def split_name_and_location(raw: str) -> Dict[str, Optional[str]]:
    """
    Extracts trailing parenthetical location, if present.
    """
    raw = raw or ""
    raw_clean = normalize_whitespace_basic(raw)
    loc = None
    m = LOCATION_IN_PARENS_PAT.search(raw_clean)
    if m:
        loc = normalize_whitespace_basic(m.group(1))
        name_part = raw_clean[: m.start()].strip()
    else:
        name_part = raw_clean
    return {"name": name_part or None, "location": loc}


def parse_inventors(raw_inventors_text: str) -> List[Dict[str, Optional[str]]]:
    """
    Returns a list of {raw, name, location, normalized_name}.
    We do not attempt aggressive firstname/lastname parsing because formats vary.
    """
    raw_inventors_text = raw_inventors_text or ""
    chunks = [c.strip() for c in INVENTOR_SPLIT_PAT.split(raw_inventors_text) if c.strip()]
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


def extract_inventors(front_text: str, inid_blocks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    # Primary: (72) if present
    if "72" in inid_blocks:
        raw = inid_blocks["72"]["text"].strip()
        span = inid_blocks["72"]["span"]
    # Fallback: (75) Inventors
    elif "75" in inid_blocks:
        raw = inid_blocks["75"]["text"].strip()
        span = inid_blocks["75"]["span"]
    else:
        # Fallback: search label directly
        m = re.search(r"\bInventors?\s*[:\-]\s*(.+)", front_text, flags=re.IGNORECASE)
        if not m:
            return {"raw": None, "value": None, "span": None, "parsed": []}
        raw = m.group(1).strip()
        span = {"start": m.start(1), "end": m.end(1)}

    raw = strip_leading_label(raw, ["Inventors", "Inventor"])
    parsed = parse_inventors(raw)

    return {"raw": raw, "value": raw, "span": span, "parsed": parsed}


ABSTRACT_HEAD_PAT = re.compile(
    r"\(\s*57\s*\)\s*ABSTRACT\b|^\s*ABSTRACT\b",
    re.IGNORECASE | re.MULTILINE,
)

REPORTED_COUNTS_PAT = re.compile(
    r"\b(\d+)\s+Claims?\s*,\s*(\d+)\s+Drawing\s+Sheets?\b",
    re.IGNORECASE,
)


def extract_abstract(front_text: str) -> Dict[str, Any]:
    """
    Returns { "text": str, "span": {...}, "heading_span": {...} } best-effort.
    Starts abstract at the END of the heading match (so '(57) ABSTRACT' is excluded).
    """
    hm = ABSTRACT_HEAD_PAT.search(front_text)
    if not hm:
        return {"text": "", "span": None, "heading_span": None}

    abs_start = hm.end()
    abs_end = len(front_text)

    # If reported counts line appears after abstract heading, stop before it
    cm = REPORTED_COUNTS_PAT.search(front_text)
    if cm and cm.start() > hm.start():
        abs_end = cm.start()

    text = front_text[abs_start:abs_end].strip()
    return {
        "text": text,
        "span": {"start": abs_start, "end": abs_end},
        "heading_span": {"start": hm.start(), "end": hm.end()},
    }


def extract_reported_counts(front_text: str) -> Optional[Dict[str, Any]]:
    m = REPORTED_COUNTS_PAT.search(front_text)
    if not m:
        return None
    return {
        "reported_claim_count": int(m.group(1)),
        "reported_drawing_sheet_count": int(m.group(2)),
        "source_snippet": m.group(0),
        "span": {"start": m.start(), "end": m.end()},
    }


US_PAT_DOCS_HEAD = re.compile(r"^\s*U\.S\.\s*PATENT\s*DOCUMENTS\s*$", re.IGNORECASE | re.MULTILINE)
FOREIGN_PAT_DOCS_HEAD = re.compile(
    r"^\s*FOREIGN\s*PATENT\s*DOCUMENTS\s*$", re.IGNORECASE | re.MULTILINE
)
OTHER_PUB_HEAD = re.compile(r"^\s*OTHER\s*PUBLICATIONS\s*$", re.IGNORECASE | re.MULTILINE)


def extract_references_by_headings(front_text: str) -> Dict[str, Any]:
    """
    Pulls the references region from the first occurrence of U.S. PATENT DOCUMENTS
    up to the ABSTRACT heading (or reported counts, or end).
    """
    m_us = US_PAT_DOCS_HEAD.search(front_text)
    if not m_us:
        return {"raw": "", "span": None, "cited_us_patents": []}

    start = m_us.start()

    # Prefer end at Abstract heading; else end at counts line; else end of page.
    m_abs = ABSTRACT_HEAD_PAT.search(front_text)
    m_counts = REPORTED_COUNTS_PAT.search(front_text)

    candidates = [len(front_text)]
    if m_abs and m_abs.start() > start:
        candidates.append(m_abs.start())
    if m_counts and m_counts.start() > start:
        candidates.append(m_counts.start())

    end = min(candidates)
    raw = front_text[start:end].strip()

    cited_us = extract_cited_us_patents_anywhere(raw)

    return {"raw": raw, "span": {"start": start, "end": end}, "cited_us_patents": cited_us}


def normalize_us_patent_header(raw: str) -> Optional[str]:
    """
    "US 7,629,993 B2" -> "US7629993B2"
    """
    if not raw:
        return None
    digits = normalize_patent_number_digits(raw)
    if not digits:
        return None
    kind = None
    mk = re.search(r"\b([A-Z]\d)\b", raw)  # e.g., B2
    if mk:
        kind = mk.group(1)
    return f"US{digits}{kind or ''}"


ASSIGNEE_STOP_PAT = re.compile(
    r"(\(\*\)|\*|\bNotice\b\s*[:\-]|\bpatent\s+is\s+extended\s+or\s+adjusted\b)",
    re.IGNORECASE,
)


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

    # Remove leading label
    raw2 = strip_leading_label(raw, ["Assignee", "Assignee:"])

    # Cut at boilerplate
    m = ASSIGNEE_STOP_PAT.search(raw2)
    assignee_only = raw2[: m.start()].strip() if m else raw2.strip()

    # Canonical: do NOT store the notice at all (per your requirement)
    return {"raw": raw, "value": assignee_only or None, "span": span}


def parse_front_page(front_text: str) -> Dict[str, Any]:
    inid = parse_inid_blocks(front_text)

    qa_warnings: List[str] = []
    qa_info: Dict[str, Any] = {}

    # -----------------------------
    # Title (54) - keep full block
    # -----------------------------
    title = extract_title_between(front_text)
    if not title:
        qa_warnings.append("missing_inid_54_title")

    # -----------------------------
    # Assignee (73/71) + Notice split
    # -----------------------------
    assignee_raw = None
    assignee_span = None
    if "73" in inid:
        assignee_raw = inid["73"]["text"].strip()
        assignee_span = inid["73"]["span"]
    elif "71" in inid:
        assignee_raw = inid["71"]["text"].strip()
        assignee_span = inid["71"]["span"]
    else:
        qa_warnings.append("missing_inid_73_or_71_assignee")

    assignee_notice = None
    assignee_clean = None
    if assignee_raw:
        assignee_clean, assignee_notice = split_assignee_and_notice(assignee_raw)

    # -----------------------------
    # Inventors (72)
    # -----------------------------
    inventors_raw = None
    inventors_span = None
    inventors_struct: List[Dict[str, Optional[str]]] = []
    if "72" in inid:
        inventors_raw = inid["72"]["text"].strip()
        inventors_span = inid["72"]["span"]
        inventors_raw = strip_leading_label(inventors_raw, ["Inventors", "Inventor"])
        inventors_struct = parse_inventors(inventors_raw)
        if not inventors_struct:
            qa_warnings.append("inventors_present_but_empty_after_parse")
    else:
        qa_warnings.append("missing_inid_72_inventors")

    # -----------------------------
    # Application number (21) - strip prefix
    # -----------------------------
    appl_raw = inid.get("21", {}).get("text")
    appl_span = inid.get("21", {}).get("span")
    appl_clean = strip_leading_label(
        appl_raw or "", ["Appl. No.", "Appl No.", "Application No.", "Application No"]
    )
    appl_clean = appl_clean or None
    if not appl_clean:
        qa_warnings.append("missing_or_empty_application_number")

    # -----------------------------
    # Filed date (22) - strip prefix + parse
    # -----------------------------
    filed_raw = inid.get("22", {}).get("text")
    filed_span = inid.get("22", {}).get("span")
    filed_clean = strip_leading_label(filed_raw or "", ["Filed"])
    filed_iso = parse_uspto_date_to_iso(filed_clean) if filed_clean else None
    if filed_raw and not filed_iso:
        qa_warnings.append("filed_date_unparsed")

    # -----------------------------
    # Grant date (45) or "Date of Patent:" - strip prefix + parse
    # -----------------------------
    grant_raw = inid.get("45", {}).get("text")
    grant_span = inid.get("45", {}).get("span")

    # fallback: look for "Date of Patent:" if (45) is not clean
    if not grant_raw:
        m = re.search(r"Date of Patent\s*[:\-]\s*([A-Za-z\.]+\s+\d{1,2},\s+\d{4})", front_text)
        if m:
            grant_raw = m.group(0)  # includes label for provenance; we'll strip it
            grant_span = {"start": m.start(), "end": m.end()}

    grant_clean = strip_leading_label(grant_raw or "", ["Date of Patent"])
    grant_iso = parse_uspto_date_to_iso(grant_clean) if grant_clean else None
    if grant_raw and not grant_iso:
        qa_warnings.append("grant_date_unparsed")

    # -----------------------------
    # Patent number: normalize digits + kind code
    # -----------------------------
    patent_header = None
    patent_header_span = None
    mh = PATENT_HEADER_PAT.search(front_text)
    if mh:
        patent_header = mh.group(0)
        patent_header_span = {"start": mh.start(), "end": mh.end()}
    else:
        qa_warnings.append("missing_patent_header_number")

    patent_digits = normalize_patent_number_digits(patent_header or "")
    patent_display = comma_format_us_patent(patent_digits) if patent_digits else None
    kind_code = None
    if patent_header:
        mk = KIND_CODE_PAT.search(patent_header)
        kind_code = mk.group(0) if mk else None

    if patent_header and not patent_digits:
        qa_warnings.append("patent_number_digits_not_found")

    # -----------------------------
    # Reported counts line + span (as before)
    # -----------------------------
    reported_counts_obj = extract_reported_counts(front_text)
    if not reported_counts_obj:
        qa_warnings.append("missing_reported_counts")

    # -----------------------------
    # Abstract: keep only text AFTER heading
    # -----------------------------
    abstract_obj = extract_abstract(front_text)
    if not abstract_obj["text"]:
        qa_warnings.append("missing_abstract")

    # Front matter span: everything before abstract heading if exists
    if abstract_obj["heading_span"]:
        fm_span = {"start": 0, "end": abstract_obj["heading_span"]["start"]}
        front_matter = front_text[0 : fm_span["end"]].strip()
    else:
        fm_span = {"start": 0, "end": len(front_text)}
        front_matter = front_text.strip()

    # -----------------------------
    # References (56): always try to parse
    # -----------------------------
    refs_raw = inid.get("56", {}).get("text") or ""
    refs_span = inid.get("56", {}).get("span")
    cited_us = extract_cited_us_patents_anywhere(
        refs_raw or front_text
    )  # fallback: search whole front page
    if not cited_us:
        qa_warnings.append("no_cited_us_patents_found")

    # -----------------------------
    # QA diagnostics
    # -----------------------------
    qa_info["inid_codes_found"] = sorted(list(inid.keys()))
    qa_info["cited_us_patent_count"] = len(cited_us)
    qa_info["inventor_count"] = len(inventors_struct)
    qa_info["has_notice_in_assignee"] = bool(assignee_notice)
    if reported_counts_obj:
        qa_info["reported_claim_count"] = reported_counts_obj["reported_claim_count"]
        qa_info["reported_drawing_sheet_count"] = reported_counts_obj[
            "reported_drawing_sheet_count"
        ]

    return {
        "raw_text": front_text,
        "inid_blocks": inid,
        "qa": {
            "warnings": qa_warnings,
            "info": qa_info,
        },
        "front_matter": front_matter,
        "front_matter_span": fm_span,
        "title": title,
        "assignee": {
            "raw": assignee_raw,
            "value": assignee_clean,
            "notice": assignee_notice,
            "span": assignee_span,
        },
        "inventors": {
            "raw": inventors_raw,
            "value": inventors_raw,  # cleaned of leading label
            "span": inventors_span,
            "parsed": inventors_struct,  # list of {raw,name,location,normalized_name}
        },
        "application_no": {
            "raw": appl_raw,
            "value": appl_clean,
            "span": appl_span,
        },
        "filed": {
            "raw": filed_raw,
            "value": filed_clean or None,
            "iso": filed_iso,
            "span": filed_span,
        },
        "grant_date": {
            "raw": grant_raw,
            "value": grant_clean or None,
            "iso": grant_iso,
            "span": grant_span,
        },
        "patent_number": {
            "raw": patent_header,
            "span": patent_header_span,
            "digits": patent_digits,
            "display": patent_display,
            "kind_code": kind_code,
        },
        "reported_counts": reported_counts_obj,  # includes spans/snippet
        "abstract": {
            "value": abstract_obj["text"],
            "span": abstract_obj["span"],
            "heading_span": abstract_obj["heading_span"],
        },
        "references_cited": {
            "raw": refs_raw,
            "span": refs_span,
            "cited_us_patents": cited_us,  # list of {digits, display}
        },
    }


if __name__ == "__main__":
    path = "/Users/Kit/Downloads/submitted.pdf"

    from pypdf import PdfReader
    from extract import extract_page_text

    reader = PdfReader(path)
    n_pages = len(reader.pages)

    # 1) Front page
    front_text = extract_page_text(reader, 0, is_front_page=True)
    # print(front_text)
    front_page = parse_front_page(front_text)

    for key, value in front_page.items():
        if (key != "raw_text") & (key != "inid_blocks"):
            print(f"{key}: {value}")
