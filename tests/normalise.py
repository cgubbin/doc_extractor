from __future__ import annotations

import re

# --- whitespace + punctuation normalization ---
_WS_RE = re.compile(r"\s+")
_NBSP_RE = re.compile(r"[\u00A0\u2007\u202F]")
_SOFT_HYPHEN_RE = re.compile(r"\u00AD")
_HYPHEN_LINEBREAK_RE = re.compile(r"(\w)-\s*\n\s*(\w)")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:])")
_SPACE_AFTER_OPEN_RE = re.compile(r"([(\[{])\s+")
_SPACE_BEFORE_CLOSE_RE = re.compile(r"\s+([)\]}])")
_SPACE_AROUND_SLASH_RE = re.compile(r"\s*/\s*")
_SPACE_AROUND_DASH_RE = re.compile(r"\s*-\s*")

# Fix common "US 123 , 123" numeric punctuation spacing
_COMMA_NUM_SERIES_RE = re.compile(r"(\d)\s*,\s*(\d)")


def normalise_text(s: str) -> str:
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


# --- OCR-aware canonicalization for "code-like tokens" (IPC/CPC, classes, dates in parens, etc) ---

_CODE_TOKEN_RE = re.compile(r"[A-Z0-9][A-Z0-9/.\-]*")
_HAS_DIGIT_RE = re.compile(r"\d")
_HAS_ALPHA_RE = re.compile(r"[A-Z]")

# Canonical mapping INSIDE code-like contexts
# Choose canonical "digits stay digits"
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

# Fix patterns like "GOIN 21/88" where the letter-only prefix is followed by a numeric fraction token.
_CODE_PREFIX_FRACTION_RE = re.compile(r"\b([A-Z]{3,6})\s+(\d{1,3}/\d{1,4})\b")


def _normalise_code_tokens(s: str) -> str:
    """
    Canonicalize OCR confusions *only* inside code-like tokens.

    Pass 1: translate tokens that already contain digits.
    Pass 2: translate letter-only prefixes when followed by N/M fraction token (e.g. GOIN 21/88).
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
    """
    Normalization for substring/contains assertions.
    - normalises whitespace/punct
    - applies code-token OCR canonicalization (scoped)
    """
    s = normalise_text(s)
    s = _normalise_code_tokens(s)
    return s
