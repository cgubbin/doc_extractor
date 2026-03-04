# from __future__ import annotations
#
import re
from dataclasses import dataclass
from typing import Literal
import statistics
from typing import List


from .model import PageLayout
from .segment_inid import inid_label_count


@dataclass()
class PageType:
    kind: Literal["inid", "body", "drawing", "unknown"]
    # inid_labels: int
    inids: int
    # para_markers: int
    paras: int


# --- drawing header ---
SHEET_RE = re.compile(r"\bSheet\s+\d+\s+of\s+\d+\b", re.IGNORECASE)

# --- certificate/admin detection ---
CERT_RE = re.compile(r"\bCERTIFICATE\s+OF\s+CORRECTION\b", re.IGNORECASE)
USPTO_RE = re.compile(
    r"\bUNITED\s+STATES\s+PATENT\s+AND\s+TRADEMARK\s+OFFICE\b", re.IGNORECASE
)

# --- claim detection ---
WHAT_CLAIMED_RE = re.compile(r"\bwhat\s+is\s+claimed\s+is\b", re.IGNORECASE)
CLAIM_LINE_RE = re.compile(r"^\s*\d{1,3}\.\s+\S")  # "13. The method ..."
CLAIMS_HEADER_RE = re.compile(r"^\s*CLAIMS\s*$", re.IGNORECASE)

# --- body heading detection ---
KNOWN_BODY_HEADINGS = {
    "BACKGROUND",
    "BACKGROUND OF THE INVENTION",
    "SUMMARY",
    "SUMMARY OF THE INVENTION",
    "BRIEF DESCRIPTION OF THE DRAWINGS",
    "DETAILED DESCRIPTION",
    "DETAILED DESCRIPTION OF THE EMBODIMENTS",
    "FIELD",
    "TECHNICAL FIELD",
    "DESCRIPTION",
    "CLAIMS",
}

# INID_RE = re.compile(r"^\s*\(\d{2}\)\s*$|^\s*\(\d{2}\)\b")


@dataclass
class PageType:
    kind: Literal["inid", "drawing", "body", "admin", "unknown"]
    inids: int = 0


def _iter_text(layout: PageLayout, region: str = "body") -> List[str]:
    reg = getattr(layout, region)
    out: List[str] = []
    for col in ("L", "R"):
        out.extend((ln.text or "").strip() for ln in reg[col].lines)
    return [t for t in out if t]


def _header_text(layout: PageLayout) -> str:
    return " ".join(_iter_text(layout, region="header"))


def _has_heading(body_lines: List[str]) -> bool:
    for t in body_lines[:80]:
        u = t.strip().upper()
        if u in KNOWN_BODY_HEADINGS:
            return True
    return False


def _claim_signal(body_lines: List[str]) -> bool:
    # Strong signals
    joined_head = " ".join(body_lines[:60])
    if WHAT_CLAIMED_RE.search(joined_head):
        return True

    # "CLAIMS" header line
    if any(CLAIMS_HEADER_RE.match(t.strip()) for t in body_lines[:80]):
        return True

    # Repeated claim enumerations
    claim_like = sum(1 for t in body_lines[:120] if CLAIM_LINE_RE.match(t))
    # 2 is enough to avoid false positives, but catches continuation pages
    return claim_like >= 2


def _density_signal(
    body_lines: List[str], *, min_lines: int, min_median_len: int
) -> bool:
    if len(body_lines) < min_lines:
        return False
    lens = [len(t) for t in body_lines]
    med = int(statistics.median(lens)) if lens else 0
    return med >= min_median_len


def classify_page(
    layout: PageLayout,
    *,
    min_inids: int = 3,
    # body density fallback thresholds (tuneable)
    min_body_lines: int = 18,
    min_median_len: int = 18,
) -> PageType:
    """
    Robust classification:
      - drawing: Sheet X of Y
      - admin: Certificate of Correction, USPTO office memo pages
      - inid: many (dd) labels
      - body: headings OR claims signal OR density fallback
      - unknown: last resort
    """

    header = _header_text(layout)
    if SHEET_RE.search(header):
        return PageType("drawing", inids=0)

    body_lines = _iter_text(layout, region="body")

    # Admin/certificate pages: detect from body first (these pages often have simple headers)
    body_head = " ".join(body_lines[:60])
    if CERT_RE.search(body_head) or USPTO_RE.search(body_head):
        return PageType("admin", inids=0)

    # INID page
    inid_count = inid_label_count(layout.body["L"]) + inid_label_count(layout.body["R"])
    if inid_count >= min_inids:
        return PageType("inid", inids=inid_count)

    # Body page signals (in order of strength)
    if _has_heading(body_lines):
        return PageType("body", inids=inid_count)

    if _claim_signal(body_lines):
        return PageType("body", inids=inid_count)

    if _density_signal(
        body_lines, min_lines=min_body_lines, min_median_len=min_median_len
    ):
        return PageType("body", inids=inid_count)

    return PageType("unknown", inids=inid_count)
