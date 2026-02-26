from __future__ import annotations

import re
from typing import Iterable, Set

from tests.normalise import normalise_for_contains
from tests.us_parse_pub import parse_us_pub_from_ocr_fragment


# IPC/CPC tokens like "G01N 21/88", "H01J 37/3255"
IPC_RE = re.compile(r"\b[A-H][0-9]{2}[A-Z]\s*\d{1,3}/\d{1,4}\b")

# US class tokens like "700/109", "438/14", "315/111.21" (allow decimal part)
USCL_RE = re.compile(r"\b\d{1,4}/\d{1,4}(?:\.\d+)?\b")


# US class tokens like "700/109", "438/14", "315/111.21" (allow decimal part)
APP_ID_RE = re.compile(r"\b\d{1,2}/\d{1,4}(?:\.\d+)?\b")

# Generic alnum "code-ish" tokens for fallback (e.g. "2006.01", "2011.01")
CODEISH_RE = re.compile(r"\b[A-Z0-9][A-Z0-9/.\-]{3,}\b")


# --- Patent identifier tokens ---
# Prefixed (explicit country):
#   US 1,123,321 B1
#   US9587932B2
#   US 2011/0054659 A1
#   US20110054659A1
#
# Bare US-style (common in (56) refs):
#   1,123,321 B1
#   2005/0000000 A1

COUNTRY = r"(?:US|WO|EP|JP|CN)"

# Prefixed, strict-ish:
PATENT_ID_PREFIXED_RE = re.compile(
    rf"\b{COUNTRY}\s*"
    r"(?:"
    r"\d{4}(?:\s*/\s*|\s+)?\d{6,8}"  # 2004/0061779 or 20040061779
    r"|"
    r"\d{1,3}(?:,\d{3}){1,3}"  # 1,123,321
    r"|"
    r"\d{7,9}"  # 7629993
    r")\s*"
    r"[A-Z0-9]\d\b",  # kind code; allow OCR digit in kind letter slot
    re.IGNORECASE,
)

# Bare US publication: 2005/0000000 A1  (must have kind)
BARE_US_PUB_RE = re.compile(
    r"\b(19\d{2}|20\d{2})\s*/\s*\d{6,8}\s*[A-Z0-9]\d\b",
    re.IGNORECASE,
)

# Bare US grant: 1,234,567 B1  (must have kind)
BARE_US_GRANT_RE = re.compile(
    r"\b\d{1,3}(?:,\d{3}){1,3}\s*[A-Z0-9]\d\b",
    re.IGNORECASE,
)


def _canonicalize_patent_id(tok: str) -> str:
    """
    Canonical form:
      - uppercase
      - remove spaces, slashes, commas
      - fix OCR in kind letter slot: '82' -> 'B2' (only at penultimate char)
    """
    t = tok.upper().replace(" ", "").replace("/", "").replace(",", "")

    # Fix OCR in KIND letter position: e.g. "...82" -> "...B2"
    if len(t) >= 2:
        kind_letter = t[-2]
        kind_digit = t[-1]
        if kind_letter.isdigit() and kind_digit.isdigit():
            if kind_letter == "8":
                t = t[:-2] + "B" + t[-1]
            elif kind_letter == "4":
                # Optional: if you see A1 -> 41 in the wild
                t = t[:-2] + "A" + t[-1]

    return t


def extract_patent_id_tokens(
    text: str,
    *,
    include_bare_us: bool = True,
) -> Set[str]:
    """
    Extract normalized patent/publication identifiers.
    - Prefixed ids keep their country prefix (US/WO/EP/JP/CN).
    - Bare US-style ids (common in references) are normalized by adding 'US' prefix.

    Canonical outputs:
      US20040061779A1
      US1123321B1
      US6878301B2
      WO2009123456A1
    """
    s = normalise_for_contains(text)
    out: Set[str] = set()

    # 1) Prefixed ids
    for m in PATENT_ID_PREFIXED_RE.findall(s):
        out.add(_canonicalize_patent_id(m))

    if include_bare_us:
        # 2) Bare US pub ids (YYYY/NNNNNNN kind)
        for m in BARE_US_PUB_RE.findall(s):
            # findall returns full match only if we avoid capture groups; we used capture for year
            # so use finditer instead for bare pub:
            pass

        # use finditer to avoid capture complications
        for m in BARE_US_PUB_RE.finditer(s):
            tok = _canonicalize_patent_id(m.group(0))
            if not tok.startswith("US"):
                tok = "US" + tok
            out.add(tok)

        # 3) Bare US grant ids (N,NNN,NNN kind)
        for m in BARE_US_GRANT_RE.finditer(s):
            tok = _canonicalize_patent_id(m.group(0))
            if not tok.startswith("US"):
                tok = "US" + tok
            out.add(tok)

    # after prefixed and bare patterns:
    if include_bare_us:
        out |= parse_us_pub_from_ocr_fragment(s)

    return out


def extract_ipc_tokens(text: str) -> Set[str]:
    s = normalise_for_contains(text)
    # normalise spaces out for stable comparison
    return {t.replace(" ", "") for t in IPC_RE.findall(s)}


def extract_uscl_tokens(text: str) -> Set[str]:
    s = normalise_for_contains(text)
    return set(USCL_RE.findall(s))


def extract_codeish_tokens(text: str) -> Set[str]:
    s = normalise_for_contains(text)
    return set(CODEISH_RE.findall(s))


US_APP_RE = re.compile(r"\b\d{2}\s*/\s*\d{3}(?:,\d{3})\b|\b\d{2}\s*/\s*\d{6}\b")
PCT_APP_RE = re.compile(
    r"\bPCT\s*/\s*[A-Z]{2}\s*\d{2,4}\s*/\s*\d{4,6}\b", re.IGNORECASE
)


def extract_application_id_tokens(text: str) -> Set[str]:
    """
    Extract normalized application identifiers.

    Canonical forms:
      - US: '12/527,981' -> '12/527981'  (keep slash, drop commas/spaces)
      - PCT: 'PCT/US08/54913' -> 'PCT/US08/54913' (uppercase, normalized slashes, no spaces)
    """
    s = normalise_for_contains(text)
    out: Set[str] = set()

    # US application serials
    for m in US_APP_RE.findall(s):
        tok = m.upper().replace(" ", "")
        tok = tok.replace(",", "")
        # normalize spacing around slash already handled in normalize_for_contains()
        out.add(tok)

    # PCT application numbers
    for m in PCT_APP_RE.findall(s):
        tok = m.upper().replace(" ", "")
        out.add(tok)

    return out


def levenshtein(a: str, b: str) -> int:
    """Small DP Levenshtein distance; suitable for short token comparisons."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(
                min(
                    prev[j] + 1,
                    cur[j - 1] + 1,
                    prev[j - 1] + (ca != cb),
                )
            )
        prev = cur
    return prev[-1]


def assert_tokens_present(
    expected: Iterable[str],
    got_tokens: Set[str],
    *,
    fuzzy: bool = False,
    max_dist: int = 1,
    label: str = "token",
) -> None:
    """
    Assert each expected token appears in got_tokens.
    If fuzzy=True, accept tokens within Levenshtein distance <= max_dist.
    """
    got_u = {t.upper() for t in got_tokens}
    for e in expected:
        eu = e.upper()
        if eu in got_u:
            continue
        if not fuzzy:
            raise AssertionError(
                f"Missing {label}: {e!r}\nGot tokens(sample)={sorted(list(got_u))[:40]}"
            )
        best = min((levenshtein(eu, g) for g in got_u), default=999)
        if best > max_dist:
            raise AssertionError(
                f"Missing {label} (fuzzy): {e!r} best_dist={best} max_dist={max_dist}\n"
                f"Got tokens(sample)={sorted(list(got_u))[:40]}"
            )
