"""Text normalization and cleaning utilities.

This module contains functions for cleaning and normalizing text extracted from
PDF patents, including whitespace normalization, dehyphenation, and punctuation
spacing fixes.
"""

import re
import unicodedata
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


# =============================================================================
# Advanced text normalization for matching and code tokens
# =============================================================================

# Whitespace and punctuation normalization patterns
_WS_RE = re.compile(r"\s+")
_NBSP_RE = re.compile(r"[\u00A0\u2007\u202F]")
_SOFT_HYPHEN_RE = re.compile(r"\u00AD")
_HYPHEN_LINEBREAK_RE = re.compile(r"(\w)-\s*\n\s*(\w)")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[{])\s+")
_SPACE_BEFORE_CLOSE_RE = re.compile(r"\s+([)\]}])")
_SPACE_AROUND_SLASH_RE = re.compile(r"\s*/\s*")
_SPACE_AROUND_DASH_RE = re.compile(r"\s*-\s*")
_COMMA_NUM_SERIES_RE = re.compile(r"(\d)\s*,\s*(\d)")

# OCR-aware canonicalization patterns
_CODE_TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9/.\-]*")
_HAS_DIGIT_RE = re.compile(r"\d")
_HAS_ALPHA_RE = re.compile(r"[A-Z]")
_CODE_PREFIX_FRACTION_RE = re.compile(r"\b([A-Z]{3,6})\s+(\d{1,3}/\d{1,4})\b")

# Canonical mapping for code-like contexts (digits stay digits)
_CODE_CHAR_MAP = str.maketrans(
    {
        "O": "0",
        "I": "1",
        "L": "1",
        "S": "5",
        "B": "8",
        "Z": "2",
    }
)


def normalise_text(s: str) -> str:
    """Normalize text with comprehensive whitespace and punctuation fixes.

    Handles:
    - Line endings (\\r\\n, \\r -> \\n)
    - Soft hyphens and non-breaking spaces
    - Hyphenated line breaks
    - Punctuation spacing (commas, periods, brackets, slashes, dashes)
    - Numeric comma series (e.g., "123 , 456" -> "123,456")

    Args:
        s: Input text

    Returns:
        Normalized text with proper spacing and punctuation
    """
    if not s:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = _SOFT_HYPHEN_RE.sub("", s)
    s = _NBSP_RE.sub(" ", s)
    s = _HYPHEN_LINEBREAK_RE.sub(r"\1\2", s)

    s = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", s)
    s = _SPACE_AFTER_OPEN_RE.sub(r"\1", s)
    s = _SPACE_BEFORE_CLOSE_RE.sub(r"\1", s)
    s = _SPACE_AROUND_SLASH_RE.sub("/", s)
    s = _SPACE_AROUND_DASH_RE.sub("-", s)

    while True:
        new = _COMMA_NUM_SERIES_RE.sub(r"\1,\2", s)
        if new == s:
            break
        s = new

    s = _WS_RE.sub(" ", s).strip()
    return s


def _normalise_code_tokens(s: str) -> str:
    """Canonicalize OCR confusions only inside code-like tokens.

    Pass 1: translate tokens that already contain digits.
    Pass 2: translate letter-only prefixes when followed by N/M fraction token (e.g. GOIN 21/88).

    Args:
        s: Input text containing code-like tokens

    Returns:
        Text with OCR confusions fixed in code tokens
    """
    up = s.upper()

    def repl(m: re.Match) -> str:
        tok = m.group(0)
        has_d = bool(_HAS_DIGIT_RE.search(tok))
        has_a = bool(_HAS_ALPHA_RE.search(tok))
        if has_d and (has_a or "/" in tok or "." in tok or "-" in tok):
            return tok.translate(_CODE_CHAR_MAP)
        return tok

    up = _CODE_TOKEN_RE.sub(repl, up)

    def repl_pair(m: re.Match) -> str:
        prefix = m.group(1).translate(_CODE_CHAR_MAP)
        frac = m.group(2)
        return f"{prefix} {frac}"

    up = _CODE_PREFIX_FRACTION_RE.sub(repl_pair, up)
    return up


def normalise_for_contains(s: str) -> str:
    """Normalization for substring/contains assertions.

    Combines:
    - Standard text normalization (whitespace/punct)
    - Code-token OCR canonicalization (scoped)

    Args:
        s: Input text

    Returns:
        Text normalized for substring matching
    """
    s = normalise_text(s)
    s = _normalise_code_tokens(s)
    return s


def normalize_for_matching(s: str) -> str:
    """Normalize text for fuzzy matching.

    Applies:
    - Unicode normalization (NFKC)
    - Case folding
    - Punctuation normalization
    - Whitespace collapsing

    Safe for headings, tokens, matching.
    NOT for preserving original text.

    Args:
        s: Input text

    Returns:
        Normalized text for fuzzy matching
    """
    if not s:
        return ""

    # Unicode normalization
    s = unicodedata.normalize("NFKC", s)

    # Case fold (better than lower())
    s = s.casefold()

    # Normalize common punctuation variants
    s = s.replace("–", "-").replace("—", "-")
    s = s.replace("'", "'").replace(""", '"').replace(""", '"')

    # Remove stray punctuation spacing
    s = re.sub(r"\s*([:/\-.,;])\s*", r"\1", s)

    # Collapse whitespace
    s = re.sub(r"\s+", " ", s)

    return s.strip()


def canonicalize_codeish_digits(s: str) -> str:
    """Canonicalize OCR-confused characters in code-like strings.

    Use ONLY on identifiers / classifications, not prose.

    Args:
        s: Code-like string (e.g., patent classification)

    Returns:
        String with OCR confusions fixed (O->0, I->1, L->1)
    """
    if not s:
        return ""

    # Uppercase first (codes are uppercase by convention)
    s = s.upper()

    # Common OCR confusions
    s = s.replace("O", "0").replace("I", "1").replace("L", "1")

    return s
