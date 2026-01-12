from __future__ import annotations
import re
from models import SectionSpan

SECTION_PATTERNS = [
    ("abstract", re.compile(r"^\s*abstract\s*$", re.IGNORECASE | re.MULTILINE)),
    ("claims", re.compile(r"^\s*claims\s*$", re.IGNORECASE | re.MULTILINE)),
    (
        "what_is_claimed",
        re.compile(r"what\s+is\s+claimed\s+is\s*[:\-]?", re.IGNORECASE),
    ),
    (
        "description",
        re.compile(
            r"^\s*(detailed\s+description|description)\s*$",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
]


def find_claims_span(text: str) -> SectionSpan | None:
    """
    Best-effort detection of the claims section. Patent PDFs vary widely.
    """
    # Prefer explicit "CLAIMS" header if present
    m = SECTION_PATTERNS[1][1].search(text)
    start = None
    conf = 0.0
    if m:
        start = m.end()
        conf = 0.85
    else:
        m2 = SECTION_PATTERNS[2][1].search(text)
        if m2:
            start = m2.start()
            conf = 0.65

    if start is None:
        return None

    # End heuristic: next major header after start
    # Look for "ABSTRACT" or "DESCRIPTION" etc after claims start
    end = len(text)
    for name, pat in SECTION_PATTERNS:
        if name in ("claims", "what_is_claimed"):
            continue
        m3 = pat.search(text, pos=start)
        if m3:
            end = min(end, m3.start())

    if end <= start:
        end = len(text)

    return SectionSpan(name="claims", start=start, end=end, confidence=conf)
