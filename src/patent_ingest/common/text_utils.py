"""Text normalization and cleaning utilities.

This module contains functions for cleaning and normalizing text extracted from
PDF patents, including whitespace normalization, dehyphenation, and punctuation
spacing fixes.
"""

import re
from typing import Pattern


# Front page noise patterns to strip
_FRONT_STRIP_PATTERNS = [
    re.compile(r"^\s*\d+\s*$", re.MULTILINE),
]


def dehyphenate(text: str) -> str:
    """Join words split by hyphen at line end.

    Example: "inspec-\\n tion" -> "inspection"

    Args:
        text: Input text with potential line-broken hyphenated words

    Returns:
        Text with hyphenated line breaks removed
    """
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text or "")


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text.

    - Converts \\r to \\n
    - Collapses horizontal whitespace (spaces/tabs) to single space
    - Reduces 3+ newlines to 2 newlines
    - Strips leading/trailing whitespace

    Args:
        text: Input text

    Returns:
        Normalized text
    """
    text = (text or "").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_whitespace_basic(s: str) -> str:
    """Basic whitespace normalization: collapse all whitespace to single spaces.

    Args:
        s: Input string

    Returns:
        String with all whitespace collapsed to single spaces, trimmed
    """
    return re.sub(r"\s+", " ", (s or "")).strip()


def normalize_punctuation_spacing(s: str) -> str:
    """Fix common PDF-extraction spacing artifacts around punctuation.

    Examples:
        - "Oct . 20 , 2016" -> "Oct. 20, 2016"
        - "Nigel P . Smith" -> "Nigel P. Smith"
        - "Milipitas , CA" -> "Milipitas, CA"

    Does NOT attempt spelling correction.

    Args:
        s: Input string with spacing artifacts

    Returns:
        String with normalized punctuation spacing
    """
    if not s:
        return s
    t = s

    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()

    # Remove spaces before common punctuation
    t = re.sub(r"\s+([,.;:)-])", r"\1", t)

    # Remove spaces after opening brackets
    t = re.sub(r"([(-])\s*", r"\1", t)

    # Ensure a single space after punctuation when appropriate
    # (Avoid touching decimals/abbreviations too aggressively.)
    t = re.sub(r"([,;:])([^\s])", r"\1 \2", t)

    # Fix spaced month abbreviations: "Oct .", "Sept ."
    t = re.sub(
        r"\b([A-Za-z]{3,4})\.\s*", lambda m: m.group(0), t
    )  # no-op but keeps structure clear

    return t


def normalize_text_field(s: str) -> str:
    """General text field normalization.

    Applies dehyphenation, whitespace normalization, and punctuation spacing fixes.

    Args:
        s: Input text field

    Returns:
        Fully normalized text
    """
    t = s or ""
    t = dehyphenate(t)
    t = normalize_whitespace(t)
    t = normalize_punctuation_spacing(t)
    return t


def strip_front_page_noise(text: str) -> str:
    """Remove common front page noise patterns.

    Strips standalone page numbers and other noise patterns commonly found
    on patent front pages.

    Args:
        text: Front page text

    Returns:
        Cleaned text with noise patterns removed
    """
    cleaned = text or ""
    for pat in _FRONT_STRIP_PATTERNS:
        cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def cut_at_heading(s: str, pat: Pattern[str]) -> str:
    """Cut string at first occurrence of heading pattern.

    Args:
        s: Input string
        pat: Regex pattern to search for (heading marker)

    Returns:
        String up to (but not including) the heading, or original string if not found
    """
    if not s:
        return s
    m = pat.search(s)
    return s[: m.start()].strip() if m else s.strip()
