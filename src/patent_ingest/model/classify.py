# from __future__ import annotations
#
import re
from dataclasses import dataclass
from typing import Literal

#


@dataclass()
class PageType:
    kind: Literal["inid", "body", "drawing", "unknown"]
    # inid_labels: int
    inids: int
    # para_markers: int
    paras: int


#
# SHEET_RE = re.compile(r"\bSheet\s+\d+\s+of\s+\d+\b", re.IGNORECASE)
# FIG_RE = re.compile(r"^\s*Fig\.\s*\d+\b", re.IGNORECASE)
# PARA_RE = re.compile(r"^\s*\d{4}\s*[.\)]\s*")
#
#
# def _para_count(layout, region="body") -> int:
#     c = 0
#     for col in ("L", "R"):
#         for ln in layout.stream(region, col).lines:
#             if PARA_RE.match(ln.text):
#                 c += 1
#     return c
#
#
# def _header_text(layout) -> str:
#     parts = []
#     for col in ("L", "R"):
#         parts.extend(ln.text for ln in layout.header[col].lines if ln.text)
#     return " ".join(parts)
#
#
# def _body_text(layout) -> str:
#     parts = []
#     for col in ("L", "R"):
#         parts.extend(ln.text for ln in layout.body[col].lines if ln.text)
#     return " ".join(parts)
#
#
# def classify_page(layout, *, region="body"):
#     print(len(layout.body["L"].lines), len(layout.body["R"].lines))
#     inids = inid_label_count(layout.stream(region, "L")) + inid_label_count(
#         layout.stream(region, "R")
#     )
#     paras = _para_count(layout, region=region)
#
#     header = _header_text(layout)
#     body = _body_text(layout)
#
#     # 1) Drawing sheets: header "Sheet X of Y" is decisive
#     if SHEET_RE.search(header):
#         return PageType("drawing", inids, paras)
#
#     # 2) Also treat as drawing if it has Fig labels but no paragraph markers and no INID run
#     if FIG_RE.search(body) and paras == 0 and inids < 3:
#         return PageType("drawing", inids, paras)
#
#     # 3) INID / body as before
#     print(f"Classify page: inids={inids}, paras={paras}")
#     if inids >= 3 and paras < 2:
#         return PageType("inid", inids, paras)
#     if paras >= 2 and inids < 3:
#         return PageType("body", inids, paras)
#     if inids >= 3 and paras >= 2:
#         return PageType("body", inids, paras)
#
#     return PageType("unknown", inids, paras)
#
# import statistics
#
# SHEET_RE = re.compile(r"\bSheet\s+\d+\s+of\s+\d+\b", re.IGNORECASE)
#
# KNOWN_BODY_HEADINGS = {
#     "BACKGROUND",
#     "SUMMARY",
#     "DETAILED DESCRIPTION",
#     "BRIEF DESCRIPTION OF THE DRAWINGS",
#     "CLAIMS",
#     "FIELD",
#     "TECHNICAL FIELD",
# }
#
#
# def _header_text(layout) -> str:
#     parts = []
#     for col in ("L", "R"):
#         parts.extend(ln.text for ln in layout.header[col].lines if ln.text)
#     return " ".join(parts)
#
#
# def _body_lines(layout) -> list[str]:
#     out = []
#     for col in ("L", "R"):
#         out.extend((ln.text or "").strip() for ln in layout.body[col].lines)
#     return [t for t in out if t]
#
#
# def _looks_like_heading_line(t: str) -> bool:
#     u = t.strip().upper()
#     return u in KNOWN_BODY_HEADINGS
#
#
# def classify_page(
#     layout, *, min_inids: int = 3, min_body_lines: int = 25, min_median_len: int = 25
# ):
#     header = _header_text(layout)
#     if SHEET_RE.search(header):
#         return PageType("drawing", inids=0, paras=0)
#
#     body_lines = _body_lines(layout)
#
#     # your existing inid count logic
#     inids = inid_label_count(layout.body["L"]) + inid_label_count(layout.body["R"])
#     if inids >= min_inids:
#         return PageType("inid", inids=inids, paras=0)
#
#     # heading-based body signal
#     if any(_looks_like_heading_line(t) for t in body_lines[:60]):  # early part of page
#         return PageType("body", inids=inids, paras=0)
#
#     # density-based body fallback
#     if len(body_lines) >= min_body_lines:
#         lens = [len(t) for t in body_lines]
#         med = int(statistics.median(lens)) if lens else 0
#         if med >= min_median_len:
#             return PageType("body", inids=inids, paras=0)
#
#     return PageType("unknown", inids=inids, paras=0)
#


import statistics
from dataclasses import dataclass
from typing import List, Literal


from .model import PageLayout
from .segment_inid import inid_label_count

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
