from __future__ import annotations
import re
from .models import SectionSpan

def find_claims_span(text: str) -> SectionSpan | None:
    # Prefer explicit header
    m = re.search(r"(?im)^\s*claims\s*$", text)
    start = None
    conf = 0.0
    if m:
        start = m.end()
        conf = 0.85
    else:
        m2 = re.search(r"(?i)what\s+is\s+claimed\s+is\s*[:\-]?", text)
        if m2:
            start = m2.start()
            conf = 0.65
    if start is None:
        return None

    end = len(text)
    # End at next major header (best-effort)
    for pat, c in [
        (r"(?im)^\s*abstract\s*$", 0.7),
        (r"(?im)^\s*(description|detailed\s+description)\s*$", 0.7),
        (r"(?im)^\s*drawings\s*$", 0.6),
    ]:
        m3 = re.search(pat, text[start:])
        if m3:
            end = min(end, start + m3.start())
    if end <= start:
        end = len(text)
    return SectionSpan(name="claims", start=start, end=end, confidence=conf)
