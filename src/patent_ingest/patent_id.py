from typing import Optional
from dataclasses import dataclass
import re

from patent_ingest.parsed import ParsedRaw, ParsedNorm, EntityKind, INIDKind


@dataclass(frozen=True)
class USPatentId:
    """
    Canonical US patent identifier.

    Examples of raw forms you might see:
      - "US 10,123,456 B2"
      - "10,123,456"
      - "US10123456"
      - "D912,345"
      - "RE38,123"
      - "PP12,345"
    """

    number: int  # digits-only numeric part
    prefix: str = ""  # "", "D", "RE", "PP" (extend as needed)
    kind: str = "grant"  # "grant" | "publication" | "application"
    country: str = "US"
    suffix: Optional[str] = None  # e.g., "B2", "A1" if you want to preserve it

    def compact(self) -> str:
        # Machine-friendly
        return f"{self.country}{self.prefix}{self.number}"

    def human(self) -> str:
        # Human-friendly (no commas here; you can add if you like)
        base = f"{self.country} {self.prefix}{self.number}"
        return f"{base} {self.suffix}".strip()


US_PATENT_FINDER = re.compile(
    r"""
    (?ix)                       # i=IGNORECASE, x=VERBOSE
    \b
    (?:US\s*)?                  # optional "US"
    (?:(?:RE|PP|D)\s*)?         # optional prefix (RE/PP/D)
    \d[\d,\s]{3,}\d             # digits with commas/spaces, at least ~5 digits total
    (?:\s*[A-Z]\d)?             # optional kind code like A1/B2 (simple)
    \b
    """,
    re.VERBOSE | re.IGNORECASE,
)


US_PATENT_RE = re.compile(
    r"""
    (?ix)
    (?:\bUS\b[\s\-]*)?                # optional US prefix
    (?P<prefix>RE|PP|D)?\s*           # optional special prefix
    (?P<num>\d[\d,\s]{3,})            # digits with commas/spaces
    (?:\s*(?P<suffix>[A-Z]\d))?       # optional kind code like A1/B2 (very simplified)
    """,
    re.VERBOSE | re.IGNORECASE,
)


def normalize_us_patent_id(raw: ParsedRaw[str]) -> Optional[ParsedNorm[USPatentId]]:
    if raw.kind not in (EntityKind.PATENT_ID, EntityKind.APPLICATION_ID) and not (
        isinstance(raw.kind, INIDKind)
        and raw.kind in {INIDKind._11, INIDKind._21}  # if you add these later
    ):
        # Not a field we intend to normalize as a US patent/app id
        return None

    m = US_PATENT_RE.search(raw.text)
    if not m:
        return None

    prefix = (m.group("prefix") or "").upper()
    num_str = m.group("num")
    digits = re.sub(r"[^\d]", "", num_str)
    if not digits:
        return None

    number = int(digits)
    suffix = m.group("suffix") or None

    # Heuristics for kind (optional)
    kind = "grant"
    if suffix and suffix.startswith("A"):
        kind = "publication"

    value = USPatentId(number=number, prefix=prefix, kind=kind, suffix=suffix)

    return ParsedNorm(
        kind=raw.kind,
        where=raw.where,
        raw_text=raw.text,
        value=value,
        confidence=raw.confidence,
        meta={**raw.meta, "normalizer": "normalize_us_patent_id"},
    )
