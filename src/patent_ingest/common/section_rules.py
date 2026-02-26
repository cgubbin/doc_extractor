# patent_ingest/common/section_rules.py
"""
Single source of truth for patent section heading recognition.

Both the low-level block classifier (model/segment_para.py) and the
high-level section mapper (body/headings.py) import from here, so
adding a new heading variant requires exactly one edit: the _RULES tuple.

OCR tolerance is automatic: _alias_to_pattern() builds anchored regexes
that accept flexible whitespace/hyphen separators between tokens and
optional trailing punctuation (semicolon, colon, period, comma).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from patent_ingest.common.text_utils import normalize_for_matching


class SectionKey(str, Enum):
    CROSS_REFERENCE = "cross_reference_to_related_applications"
    BACKGROUND = "background"
    SUMMARY = "summary"
    BRIEF_DESCRIPTION = "brief_description_of_drawings"
    DETAILED_DESCRIPTION = "detailed_description"
    CLAIMS = "claims"
    ABSTRACT = "abstract"  # occasionally appears inside body PDFs
    OTHER = "other"


@dataclass(frozen=True)
class SectionRule:
    key: SectionKey
    # Uppercase normalized aliases — human-readable and used to auto-generate patterns.
    # To add a new variant, just add an alias here; no other file needs changing.
    aliases: tuple[str, ...]
    # Truly unusual forms that can't be captured by the alias auto-generator.
    extra_patterns: tuple[re.Pattern[str], ...] = ()


def _norm_heading_text(s: str) -> str:
    """Normalize heading text to a clean uppercase string for matching."""
    s = (s or "").strip()
    if not s:
        return ""
    s = normalize_for_matching(s)          # NFKC, casefold, punct/ws cleanup
    s = re.sub(r"[\u2013\u2014\u2212]", "-", s)  # en-dash, em-dash, minus → hyphen
    s = re.sub(r"\s+", " ", s).strip()
    return s.upper()


def _alias_to_pattern(alias: str) -> re.Pattern[str]:
    """
    Build an OCR-tolerant anchored regex from a normalized uppercase alias.

    Robustness properties:
    - Hyphens and spaces are interchangeable between tokens
      ("CROSS-REFERENCE" matches "CROSS REFERENCE" and vice versa)
    - Extra whitespace between tokens is tolerated
    - Trailing punctuation (semicolon, colon, period, comma) is optional
    - Fully anchored — will not match the alias inside a longer phrase
    """
    tokens = [t for t in re.split(r"[\s\-]+", alias) if t]
    inner = r"[\s\-]+".join(re.escape(t) for t in tokens)
    return re.compile(r"^\s*" + inner + r"[\s;:.,]*$", re.IGNORECASE)


_RULES: tuple[SectionRule, ...] = (
    SectionRule(
        key=SectionKey.CROSS_REFERENCE,
        aliases=(
            "CROSS-REFERENCE TO RELATED APPLICATIONS",
            "CROSS-REFERENCE TO RELATED APPLICATION",
        ),
    ),
    SectionRule(
        key=SectionKey.BACKGROUND,
        aliases=(
            "BACKGROUND",
            "BACKGROUND OF THE INVENTION",
            "BACKGROUND ART",
            "FIELD OF THE INVENTION",
            "TECHNICAL FIELD",
            "FIELD",
            "RELATED ART",
            "PRIOR ART",
        ),
    ),
    SectionRule(
        key=SectionKey.SUMMARY,
        aliases=(
            "SUMMARY",
            "SUMMARY OF THE INVENTION",
            "BRIEF SUMMARY",
            "BRIEF SUMMARY OF THE INVENTION",
        ),
    ),
    SectionRule(
        key=SectionKey.BRIEF_DESCRIPTION,
        aliases=(
            "BRIEF DESCRIPTION OF THE DRAWINGS",
            "DESCRIPTION OF THE DRAWINGS",
            "BRIEF DESCRIPTION OF DRAWINGS",
        ),
    ),
    SectionRule(
        key=SectionKey.DETAILED_DESCRIPTION,
        aliases=(
            "DETAILED DESCRIPTION",
            "DETAILED DESCRIPTION OF THE INVENTION",
            "DESCRIPTION OF EMBODIMENTS",
            "DETAILED DESCRIPTION OF EMBODIMENTS",
            "DETAILED DESCRIPTION OF THE EMBODIMENTS",
            "DETAILED DESCRIPTION OF THE PREFERRED EMBODIMENTS",
            "DETAILED DESCRIPTION OF PREFERRED EMBODIMENTS",
        ),
    ),
    SectionRule(
        key=SectionKey.CLAIMS,
        aliases=(
            "CLAIMS",
            "WHAT IS CLAIMED IS",
            "WHAT IS CLAIMED",
            "THE INVENTION CLAIMED IS",
        ),
    ),
)


# ---------------------------------------------------------------------------
# Precomputed lookup: (rule, (pattern, ...)) — built once at import time.
# Each alias generates one OCR-tolerant pattern; extra_patterns are appended.
# ---------------------------------------------------------------------------

_COMPILED_RULES: tuple[tuple[SectionRule, tuple[re.Pattern[str], ...]], ...] = tuple(
    (rule, tuple(_alias_to_pattern(a) for a in rule.aliases) + rule.extra_patterns)
    for rule in _RULES
)

# Reject lines that are nothing but a paragraph number (e.g. "0017", "0019.")
_PARA_NUM_ONLY = re.compile(r"^\s*\d{3,5}\s*\.?\s*$")

# Strip leading enumerators such as "I. BACKGROUND", "I.BACKGROUND", "A) SUMMARY"
# Trailing space is optional since normalize_for_matching may collapse it.
_LEADING_ROMAN = re.compile(r"^[IVXLC]+\.\s*")
_LEADING_ALPHA_PAREN = re.compile(r"^[A-Z]\)\s*")


def _strip_leading_enumerator(h: str) -> str:
    h = _LEADING_ROMAN.sub("", h)
    h = _LEADING_ALPHA_PAREN.sub("", h)
    return h.strip()


def normalize_section_heading(text: str) -> Optional[SectionKey]:
    """
    Map a raw heading string to a canonical SectionKey, or None.

    Pipeline:
      1. Reject bare paragraph numbers.
      2. Normalize (unicode, whitespace, dash variants, uppercase).
      3. Strip trailing punctuation and leading enumerators.
      4. Try each precompiled OCR-tolerant pattern.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if _PARA_NUM_ONLY.match(raw):
        return None

    h = _norm_heading_text(raw)
    # Belt-and-suspenders: strip trailing punctuation before pattern matching
    # (the patterns also accept it, but this keeps h clean for debugging).
    h = re.sub(r"[;:\-\u2013\u2014]\s*$", "", h).strip()
    h = _strip_leading_enumerator(h)

    for rule, patterns in _COMPILED_RULES:
        for p in patterns:
            if p.match(h):
                return rule.key

    return None


def is_known_section_heading(text: str) -> bool:
    """
    Return True if *text* is recognised as a known section heading.

    Intended for the low-level block classifier (segment_para.py) so it can
    emit section_heading blocks without maintaining a separate whitelist.
    """
    return normalize_section_heading(text) is not None
