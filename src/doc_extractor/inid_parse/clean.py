from __future__ import annotations

import re
from typing import Iterable

from .normalize import normalize_whitespace

# Match leading INID label at start of field: "(57)", "(57) ", "(57)\n"
# Also tolerate OCR variants like "(S7)" occasionally by allowing 0-9 and common OCR I/O?
INID_PREFIX_RE = re.compile(r"^\s*\(\s*(\d{2})\s*\)\s*", re.DOTALL)


# Some fields embed a second INID label on the next line; remove a few times.
def strip_inid_prefix(text: str, *, max_passes: int = 2) -> str:
    s = text.lstrip()
    for _ in range(max_passes):
        m = INID_PREFIX_RE.match(s)
        if not m:
            break
        s = s[m.end() :].lstrip()
    return s


def strip_leading_label(text: str, labels: Iterable[str]) -> str:
    """
    Remove a leading field label like 'ABSTRACT', 'Inventors:', 'Assignee:'.
    Only strips if it appears right at the start (after INID removal),
    and only once.
    """
    s = text.lstrip()

    # Normalize a little for matching but preserve original slicing:
    # We'll do case-insensitive regex anchored at start.
    for lab in labels:
        # allow optional punctuation and em-dash variants
        # e.g. "Assignee:" / "Attorney, Agent, or Firm—"
        pat = re.compile(
            r"^\s*" + re.escape(lab) + r"\s*[:—\-]\s*",
            re.IGNORECASE,
        )
        m = pat.match(s)
        if m:
            return s[m.end() :].lstrip()

        # Also handle labels that are standalone line headers like:
        # "ABSTRACT\n..." or "Inventors:\n..."
        pat2 = re.compile(r"^\s*" + re.escape(lab) + r"\s*\n+", re.IGNORECASE)
        m2 = pat2.match(s)
        if m2:
            return s[m2.end() :].lstrip()

    return s


def clean_inid_text(text: str) -> str:
    """
    Conservative cleaning for semantic fields:
    - strip INID prefix
    - normalize whitespace (keep line breaks reasonably)
    """
    s = strip_inid_prefix(text)
    return normalize_whitespace(s)


def clean_title(text: str) -> str:
    # Titles often contain OCR linebreak oddities; keep as lines but normalize spaces.
    s = clean_inid_text(text)
    # remove common "TITLE" label if present (rare on US, but can exist)
    s = strip_leading_label(s, ["TITLE"])
    return s


def clean_abstract(text: str) -> str:
    s = clean_inid_text(text)
    s = strip_leading_label(s, ["ABSTRACT"])
    return s


def clean_assignee(text: str) -> str:
    s = clean_inid_text(text)
    s = strip_leading_label(s, ["ASSIGNEE", "ASSIGNEE(S)"])

    # Hard-cut boilerplate that frequently follows assignee on grants
    cut_markers = [
        "(*) NOTICE:",
        "NOTICE:",
        "SUBJECT TO ANY DISCLAIMER",
        "THE TERM OF THIS PATENT",
        "PATENT TERM",
    ]
    up = s.upper()
    cut_at = None
    for mk in cut_markers:
        j = up.find(mk)
        if j != -1:
            cut_at = j if cut_at is None else min(cut_at, j)
    if cut_at is not None:
        s = s[:cut_at].rstrip()

    return s


def clean_inventors(text: str) -> str:
    s = clean_inid_text(text)
    s = strip_leading_label(s, ["INVENTOR", "INVENTORS"])
    return s


def clean_attorney(text: str) -> str:
    s = clean_inid_text(text)
    # the attorney field on USPTO pages is often "Attorney, Agent, or Firm—..."
    s = strip_leading_label(
        s,
        ["ATTORNEY, AGENT, OR FIRM", "ATTORNEY", "AGENT", "FIRM"],
    )
    return s


def clean_application_number(text: str) -> str:
    s = clean_inid_text(text)
    s = strip_leading_label(s, ["APPL. NO.", "APPLICATION NO.", "APPLICATION NUMBER"])
    return s


def clean_filing_date(text: str) -> str:
    s = clean_inid_text(text)
    s = strip_leading_label(s, ["FILED", "FILING DATE"])
    return s


def clean_grant_date(text: str) -> str:
    s = clean_inid_text(text)
    s = strip_leading_label(s, ["DATE OF PATENT"])
    return s


_ABSTRACT_TAIL_RE = re.compile(
    r"(?:\n|\s)+(?P<claims>\d{1,3})\s+CLAIMS?(?:,\s*(?P<draw>\d{1,3})\s+DRAWING\s+SHEETS?)?\s*$",
    re.IGNORECASE,
)


_CLAIMS_RE = re.compile(
    r"(?P<claims>\d{1,3})\s+CLAIMS?,?",
    re.IGNORECASE,
)

_SHEETS_RE = re.compile(
    r"(?P<draw>\d{1,3})\s+DRAWING\s+SHEETS?",
    re.IGNORECASE,
)


def split_abstract_tail(text: str) -> tuple[str, dict[str, int]]:
    """
    Returns (clean_abstract, meta) where meta may include claims_count and drawing_sheets_count.
    """
    s = text.rstrip()
    d = _SHEETS_RE.search(s)
    if not d:
        return s, {}

    s2 = s[: d.start()].rstrip()

    c = _CLAIMS_RE.search(s)
    if not c:
        return s2, {}

    s3 = s2[: c.start()].rstrip()

    meta: dict[str, int] = {
        "claims_count": int(c.group("claims")),
        "drawing_sheets_count": int(d.group("draw")),
    }

    return s3, meta
