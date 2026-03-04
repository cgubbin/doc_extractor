from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")
_SOFT_HYPHEN = "\u00ad"


def normalize_whitespace(s: str) -> str:
    s = s.replace(_SOFT_HYPHEN, "")
    s = s.replace("\r", "\n")
    # keep newlines but compress spaces
    s = re.sub(r"[ \t]+", " ", s)
    # collapse 3+ newlines to 2
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def normalize_for_matching(s: str) -> str:
    """
    Conservative normalisation for matching:
    - uppercase
    - normalize whitespace to single spaces
    - keep punctuation (we depend on '/' '.' ',' to interpret patterns)
    """
    s = normalize_whitespace(s)
    s = _WS_RE.sub(" ", s)
    return s.upper()


def canonicalize_codeish_digits(s: str) -> str:
    """
    Apply OCR fixes that are common in *code-like contexts*:
    O->0, I/L/|->1
    (Do NOT apply globally to prose.)
    """
    return s.replace("O", "0").replace("I", "1").replace("L", "1").replace("|", "1")


def canonicalize_kind(kind2: str) -> str:
    """
    Kind token normalisation: AL/AI/A| -> A1, 82 -> B2, etc.
    """
    k = kind2.upper().replace(" ", "")
    if len(k) != 2:
        return k
    if k[0] == "A" and k[1] in {"L", "I", "|"}:
        return "A1"
    # OCR where letter is read as digit
    if k[0].isdigit() and k[1].isdigit():
        if k[0] == "8":
            return "B" + k[1]
        if k[0] == "4":
            return "A" + k[1]
    return k
