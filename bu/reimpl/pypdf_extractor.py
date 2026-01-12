from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from pypdf import PdfReader


# -----------------------------
# Cleaning utilities
# -----------------------------
HEADER_FOOTER_PATTERNS_BODY = [
    re.compile(r"^US\s+\d{1,2},\d{3},\d{3}\s+B\d\s*$", re.MULTILINE),
    re.compile(r"^U\.S\.\s+Patent.*Sheet.*US\s+\d{1,2},\d{3},\d{3}\s+B\d\s*$", re.MULTILINE),
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]

HEADER_FOOTER_PATTERNS_FRONT = [
    # front page: keep the US patent number line; it is metadata we want
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]


def strip_headers_footers(text: str, *, is_front_page: bool = False) -> str:
    pats = HEADER_FOOTER_PATTERNS_FRONT if is_front_page else HEADER_FOOTER_PATTERNS_BODY
    cleaned = text
    for pat in pats:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def dehyphenate(text: str) -> str:
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_page_text(reader: PdfReader, page_index: int, *, is_front_page: bool = False) -> str:
    page = reader.pages[page_index]
    t = page.extract_text() or ""
    t = dehyphenate(t)
    t = strip_headers_footers(t, is_front_page=is_front_page)
    t = normalize_whitespace(t)
    return t


# -----------------------------
# Front-page metadata & abstract parsing
# -----------------------------
REPORTED_COUNTS_PAT = re.compile(
    r"\b(\d+)\s+Claims?\s*,\s*(\d+)\s+Drawing\s+Sheets?\b",
    re.IGNORECASE,
)

ABSTRACT_HEAD_PAT = re.compile(
    r"\(\s*57\s*\)\s*ABSTRACT\b|^\s*ABSTRACT\b", re.IGNORECASE | re.MULTILINE
)


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


PATENT_NO_PAT = re.compile(r"\bUS\s+\d{1,2},\d{3},\d{3}\s+B\d\b")
DATE_OF_PATENT_PAT = re.compile(r"Date of Patent:\s*([A-Za-z]+\.\s+\d{1,2},\s+\d{4})")


def first_line(s: str) -> str:
    return s.split("\n", 1)[0].strip()


def extract_patent_number(front_text: str) -> Optional[Dict[str, Any]]:
    m = PATENT_NO_PAT.search(front_text)
    if not m:
        return None
    return {"value": m.group(0), "span": {"start": m.start(), "end": m.end()}}


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


def parse_assignee(raw_assignee_text: str) -> Dict[str, Optional[str]]:
    """
    Best-effort split into name + location.
    """
    raw_assignee_text = raw_assignee_text or ""
    parts = split_name_and_location(raw_assignee_text)
    nm = parts["name"]
    return {
        "raw": normalize_whitespace_basic(raw_assignee_text) or None,
        "name": nm,
        "location": parts["location"],
        "normalized_name": normalize_entity_name(nm) if nm else None,
    }


US_PATENT_CITATION_PAT = re.compile(
    r"\b(\d{1,2},\d{3},\d{3})\b"  # e.g. 7,629,993 (commas present)
)


def extract_cited_us_patents(inid_56_text: str) -> List[str]:
    """
    Returns list of unique cited US patent numbers (comma-formatted),
    as they appear in the references cited section.
    """
    hits = US_PATENT_CITATION_PAT.findall(inid_56_text or "")
    # de-dup, preserve order
    seen = set()
    out = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


REFS_SECTION_HEAD_PAT = re.compile(
    r"^\s*(U\.S\.\s*PATENT\s*DOCUMENTS|FOREIGN\s*PATENT\s*DOCUMENTS|OTHER\s*PUBLICATIONS)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

US_PATENT_NO_PAT = re.compile(r"\b(\d{1,2},\d{3},\d{3})\b")  # comma-formatted US patent nos
WO_EP_DE_PAT = re.compile(
    r"\b(WO|EP|DE|FR|GB|JP|CN|KR|RU|CA|AU)\s*[-]?\s*([A-Z]?\s*\d[\d\s/.-]*)\b"
)

NONPATENT_YEAR_PAT = re.compile(r"\b(19\d{2}|20\d{2})\b")


def split_references_56(raw_56: str) -> Dict[str, str]:
    """
    Splits the (56) block into labeled buckets by common headings.
    If headings are missing, returns {"unclassified": raw_56}.
    """
    raw_56 = raw_56 or ""
    matches = list(REFS_SECTION_HEAD_PAT.finditer(raw_56))
    if not matches:
        return {"unclassified": raw_56.strip()}

    buckets: Dict[str, str] = {}
    for i, m in enumerate(matches):
        head = m.group(1).upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw_56)
        buckets[head] = raw_56[start:end].strip()
    return buckets


def extract_us_patent_numbers(text: str) -> List[str]:
    hits = US_PATENT_NO_PAT.findall(text or "")
    seen = set()
    out = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def extract_foreign_doc_tokens(text: str) -> List[str]:
    """
    Very lightweight extraction of country-code style refs like WO 2005/123456, EP 1234567, etc.
    Returns normalized token strings.
    """
    out = []
    for m in WO_EP_DE_PAT.finditer(text or ""):
        cc = m.group(1).upper()
        num = normalize_whitespace_basic(m.group(2)).replace(" ", "")
        out.append(f"{cc}{num}")
    # de-dup preserve order
    seen = set()
    uniq = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def extract_other_publications_lines(text: str) -> List[str]:
    """
    Keep as lines; optionally filter out empty. Later you can add citation parsing.
    """
    lines = [normalize_whitespace_basic(l) for l in (text or "").split("\n")]
    return [l for l in lines if l]


def parse_front_page(front_text: str) -> Dict[str, Any]:
    """
    Returns a structured front-page parse:
      - raw_text
      - inid_blocks (raw)
      - fields: title, assignee, inventors, application_no, filed, grant_date, patent_number, abstract, reported_counts, cited_us_patents
      - spans for everything we can
    """
    inid = parse_inid_blocks(front_text)

    # Title from (54)
    title = None
    title_span = None
    if "54" in inid:
        title = first_line(inid["54"]["text"])
        title_span = inid["54"]["span"]

    # Assignee: often (73); sometimes (71)
    assignee = None
    assignee_span = None
    if "73" in inid:
        assignee = first_line(inid["73"]["text"])
        assignee_span = inid["73"]["span"]
    elif "71" in inid:
        assignee = first_line(inid["71"]["text"])
        assignee_span = inid["71"]["span"]

    # Inventors from (72)
    inventors = None
    inventors_span = None
    if "72" in inid:
        inventors = inid["72"]["text"].strip()
        inventors_span = inid["72"]["span"]

    inventors_struct = parse_inventors(inventors) if inventors else []
    assignee_struct = parse_assignee(assignee) if assignee else None

    # Filing metadata
    application_no = inid.get("21", {}).get("text")
    application_no_span = inid.get("21", {}).get("span")
    filed = inid.get("22", {}).get("text")
    filed_span = inid.get("22", {}).get("span")

    # Grant date: usually (45)
    grant_date = inid.get("45", {}).get("text")
    grant_date_span = inid.get("45", {}).get("span")
    if not grant_date:
        dm = DATE_OF_PATENT_PAT.search(front_text)
        if dm:
            grant_date = dm.group(1)
            grant_date_span = {"start": dm.start(1), "end": dm.end(1)}

    patent_number_obj = extract_patent_number(front_text)
    reported_counts_obj = extract_reported_counts(front_text)
    abstract_obj = extract_abstract(front_text)

    references = {}
    if "56" in inid:
        refs_raw = inid["56"]["text"]
        refs_split = split_references_56(refs_raw)

        references = {
            "raw": refs_raw,
            "buckets": refs_split,
            "us_patent_numbers": extract_us_patent_numbers(
                refs_split.get("U.S. PATENT DOCUMENTS", refs_raw)
            ),
            "foreign_doc_tokens": extract_foreign_doc_tokens(
                refs_split.get("FOREIGN PATENT DOCUMENTS", "")
            ),
            "other_publications": extract_other_publications_lines(
                refs_split.get("OTHER PUBLICATIONS", "")
            ),
        }

    # Front matter span: everything before abstract heading if it exists
    front_matter = front_text
    front_matter_span = {"start": 0, "end": len(front_text)}
    if abstract_obj["heading_span"]:
        front_matter_span = {"start": 0, "end": abstract_obj["heading_span"]["start"]}
        front_matter = front_text[0 : abstract_obj["heading_span"]["start"]].strip()

    return {
        "raw_text": front_text,
        "inid_blocks": inid,  # raw slices keyed by code
        "front_matter": front_matter,
        "front_matter_span": front_matter_span,
        "title": {"value": title, "span": title_span},
        "assignee": {"value": assignee, "span": assignee_span},
        "assignee_struct": assignee_struct,
        "inventors": {"value": inventors, "span": inventors_span},
        "inventors_struct": inventors_struct,
        "application_no": {"value": application_no, "span": application_no_span},
        "filed": {"value": filed, "span": filed_span},
        "grant_date": {"value": grant_date, "span": grant_date_span},
        "patent_number": patent_number_obj,  # {value, span} or None
        "reported_counts": reported_counts_obj,  # {reported_claim_count,..., span} or None
        "abstract": {
            "value": abstract_obj["text"],
            "span": abstract_obj["span"],
            "heading_span": abstract_obj["heading_span"],
        },
        "references_cited": references,
    }


# -----------------------------
# Body section detection
# -----------------------------
@dataclass
class SectionSpan:
    name: str
    start: int
    end: int


SECTION_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("background", re.compile(r"^\s*BACKGROUND OF THE INVENTION\b", re.MULTILINE)),
    ("summary", re.compile(r"^\s*SUMMARY OF THE INVENTION\b", re.MULTILINE)),
    (
        "brief_description_of_drawings",
        re.compile(r"^\s*BRIEF DESCRIPTION OF THE DRAWINGS\b", re.MULTILINE),
    ),
    ("detailed_description", re.compile(r"^\s*DETAILED DESCRIPTION\b", re.MULTILINE)),
    (
        "claims",
        re.compile(r"^\s*What is claimed is\s*:\s*$|^\s*What is claimed is\s*:\s*", re.MULTILINE),
    ),
    (
        "certificate_of_correction",
        re.compile(
            r"^\s*UNITED STATES PATENT AND TRADEMARK OFFICE\b.*CERTIFICATE OF CORRECTION\b",
            re.MULTILINE | re.DOTALL,
        ),
    ),
]


def find_headings(text: str) -> List[Tuple[int, str]]:
    hits: List[Tuple[int, str]] = []
    for name, pat in SECTION_PATTERNS:
        for m in pat.finditer(text):
            hits.append((m.start(), name))
    hits.sort(key=lambda x: x[0])

    deduped: List[Tuple[int, str]] = []
    for pos, name in hits:
        if not deduped or deduped[-1][1] != name:
            deduped.append((pos, name))
    return deduped


def build_spans(text: str) -> List[SectionSpan]:
    hits = find_headings(text)
    if not hits:
        return [SectionSpan("unclassified", 0, len(text))]

    spans: List[SectionSpan] = []
    if hits[0][0] > 0:
        spans.append(SectionSpan("body_preamble", 0, hits[0][0]))

    for i, (pos, name) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        spans.append(SectionSpan(name, pos, end))

    return spans


def extract_sections(text: str) -> Dict[str, str]:
    sections: Dict[str, str] = {}
    for span in build_spans(text):
        chunk = text[span.start : span.end].strip()
        if not chunk:
            continue
        if span.name in sections:
            sections[span.name] = (sections[span.name] + "\n\n" + chunk).strip()
        else:
            sections[span.name] = chunk
    return sections


# -----------------------------
# Orchestrator: 3-phase parse
# -----------------------------
def parse_patent_pdf_three_phase(path: str) -> Dict[str, Any]:
    reader = PdfReader(path)
    n_pages = len(reader.pages)

    if n_pages == 0:
        return {"metadata": {}, "front_page": {}, "drawings": {}, "body": {}}

    # 1) Front page
    front_text = extract_page_text(reader, 0, is_front_page=True)
    front_page = parse_front_page(front_text)

    # Optional: keep for traceability (can be large; enable if you want)
    front_page["raw_text"] = front_text

    reported_drawings = None
    if front_page.get("reported_counts"):
        reported_drawings = front_page["reported_counts"]["reported_drawing_sheet_count"]
    metadata = {
        "front_page_index": 0,
        "reported_claim_count": (front_page.get("reported_counts") or {}).get(
            "reported_claim_count"
        ),
        "reported_drawing_sheet_count": reported_drawings,
        "patent_number": (front_page.get("patent_number") or {}).get("value"),
    }

    if reported_drawings is None:
        # Fallback: treat everything after page 0 as body if the marker is missing
        body_pages_text = [extract_page_text(reader, i) for i in range(1, n_pages)]
        body_text = "\n\n".join([t for t in body_pages_text if t.strip()]).strip()
        return {
            "metadata": metadata,
            "front_page": front_page,
            "drawings": {"page_indices": [], "pages_text": []},
            "body": {"sections": extract_sections(body_text), "raw_text": body_text},
        }

    # 2) Drawing sheets: pages 1..Y (bounded by document length)
    drawing_start = 1
    drawing_end_exclusive = min(1 + int(reported_drawings), n_pages)
    drawing_indices = list(range(drawing_start, drawing_end_exclusive))
    drawings_pages_text = [extract_page_text(reader, i) for i in drawing_indices]

    # 3) Body: remaining pages
    body_start = drawing_end_exclusive
    body_pages_text = [extract_page_text(reader, i) for i in range(body_start, n_pages)]
    body_text = "\n\n".join([t for t in body_pages_text if t.strip()]).strip()
    body_sections = extract_sections(body_text)

    return {
        "metadata": metadata,
        "front_page": front_page,
        "drawings": {"page_indices": drawing_indices, "pages_text": drawings_pages_text},
        "body": {"sections": body_sections, "raw_text": body_text},
    }


if __name__ == "__main__":
    path = "/Users/Kit/Downloads/granted.pdf"

    result = parse_patent_pdf_three_phase(path)
    print(result["front_page"]["references_cited"])
    # return {
    #     "raw_text": front_text,
    #     "inid_blocks": inid,  # raw slices keyed by code
    #     "front_matter": front_matter,
    #     "front_matter_span": front_matter_span,
    #     "title": {"value": title, "span": title_span},
    #     "assignee": {"value": assignee, "span": assignee_span},
    #     "inventors": {"value": inventors, "span": inventors_span},
    #     "application_no": {"value": application_no, "span": application_no_span},
    #     "filed": {"value": filed, "span": filed_span},
    #     "grant_date": {"value": grant_date, "span": grant_date_span},
    #     "patent_number": patent_number_obj,  # {value, span} or None
    #     "reported_counts": reported_counts_obj,  # {reported_claim_count,..., span} or None
    #     "abstract": {
    #         "value": abstract_obj["text"],
    #         "span": abstract_obj["span"],
    #         "heading_span": abstract_obj["heading_span"],
    #     },
    #     "cited_us_patents": cited_us_patents,
    # }
