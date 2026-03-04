from __future__ import annotations

import re
from typing import Set

from .normalize import (
    normalize_for_matching,
    canonicalize_kind,
    canonicalize_codeish_digits,
)

# Country prefixes we care about for explicit IDs
_COUNTRY = r"(?:US|WO|EP|JP|CN)"


# Prefixed (explicit) IDs: US 2011/0054659 A1, US20110054659A1, US 6,878,301 B2, etc.
PATENT_ID_PREFIXED_RE = re.compile(
    rf"\b{_COUNTRY}\s*"
    r"(?:"
    r"\d{4}(?:\s*/\s*|\s+)?\d{6,8}"
    r"|"
    r"\d{1,3}(?:,\d{3}){1,3}"
    r"|"
    r"\d{7,9}"
    r")\s*"
    r"[A-Z0-9]{2}\b",
    re.IGNORECASE,
)

# Bare US grant: 6,878,301 B2
BARE_US_GRANT_RE = re.compile(
    r"\b\d{1,3}(?:,\d{3}){1,3}\s*[A-Z0-9]{2}\b",
    re.IGNORECASE,
)

# Matches: 3,963,354 A  /  4,148,065. A  /  5,892.579 A
BARE_US_GRANT_KIND1_RE = re.compile(
    r"\b(?P<num>[\d,\.]{7,12})\s*(?P<kind>[A-Z])\b",
    re.IGNORECASE,
)

# US publication references with OCR noise:
# 2005/019 1858 A1
# 2005.0109729 A15/2009
# 2009/0296075 AL 12/2009
# Avoid matching month/year by requiring year not preceded by digit+slash.
_USPUB_RE = re.compile(
    r"(?<!\d/)\b"
    r"(?P<year>19\d{2}|20\d{2})"
    r"\s*[/\.]\s*"
    r"(?P<serial>[\d\s,\.]{6,12})"
    r"\s*(?P<kind>[A-Z0-9]{2})"
    r"(?:\s*(?:\d{1,2}\s*/\s*(?:19\d{2}|20\d{2})))?"
    r"\b",
    re.IGNORECASE,
)

# US application ids: 12/527,981 or 16/123456
US_APP_RE = re.compile(r"\b\d{2}\s*/\s*(?:\d{3}(?:,\d{3})|\d{6})\b")

# PCT ids: PCT/US08/54913, PCT/EP2010/012345
PCT_APP_RE = re.compile(
    r"\bPCT\s*/\s*[A-Z]{2}\s*\d{2,4}\s*/\s*\d{4,6}\b", re.IGNORECASE
)

# IPC/CPC (tolerant digits): G01N 21/88, GO1N 21/88, etc.
IPC_RE = re.compile(
    r"\b[A-H]"
    r"[0-9OIL]{2}"
    r"[A-Z]"
    r"\s*"
    r"[0-9OIL]{1,3}"
    r"\s*/\s*"
    r"[0-9OIL]{1,4}\b",
    re.IGNORECASE,
)

# USCL rough: 700/109, 438/14, 315/111.21
USCL_RE = re.compile(r"\b\d{1,4}\s*/\s*\d{1,4}(?:\.\d+)?\b")


def _canon_patent_token(tok: str) -> str:
    t = normalize_for_matching(tok)

    # Remove spaces but keep letters for kind correction
    t = t.replace(" ", "")

    # Apply OCR fixes for code-ish text (safe at token level)
    # Do NOT touch the "US" prefix semantics; just normalize within.
    if t.startswith("US"):
        body = t[2:]
        body = body.replace("O", "0").replace("I", "1").replace("L", "1")
        t = "US" + body

    t = t.replace("/", "").replace(",", "")

    if len(t) >= 2:
        kind = canonicalize_kind(t[-2:])
        t = t[:-2] + kind

    return t


def _canon_pub_serial(serial_raw: str) -> str | None:
    serial_raw = (
        serial_raw.upper().replace("O", "0").replace("I", "1").replace("L", "1")
    )
    digits = "".join(ch for ch in serial_raw if ch.isdigit())
    if len(digits) == 6:
        digits = "0" + digits
    if len(digits) == 8 and digits[0] == "0":
        digits = digits[1:]
    if len(digits) != 7:
        return None
    return digits


def extract_patent_id_tokens(text: str, *, include_bare_us: bool = True) -> Set[str]:
    s = normalize_for_matching(text)
    out: Set[str] = set()

    # 1) prefixed
    for m in PATENT_ID_PREFIXED_RE.finditer(s):
        out.add(_canon_patent_token(m.group(0)))

    if include_bare_us:
        # 2) bare US grants
        for m in BARE_US_GRANT_RE.finditer(s):
            tok = _canon_patent_token(m.group(0))
            if not tok.startswith("US"):
                tok = "US" + tok
            out.add(tok)

        # 3) OCR-y US publication references (year/serial kind)
        for m in _USPUB_RE.finditer(s):
            year = m.group("year")
            serial = _canon_pub_serial(m.group("serial"))
            if not serial:
                continue
            kind = canonicalize_kind(m.group("kind"))
            # Accept common kinds; extend only if you see more in practice.
            if kind not in {"A1", "A2", "A9", "B1", "B2"}:
                continue
            out.add(f"US{year}{serial}{kind}")

        # 1-letter kind (older grants in references)
        for m in BARE_US_GRANT_KIND1_RE.finditer(s):
            num_raw = m.group("num")
            kind = m.group("kind").upper()

            digits = "".join(ch for ch in num_raw if ch.isdigit())
            # US grant numbers are typically 7 digits here; be tolerant but sanity check
            if len(digits) < 6:
                continue
            # Most of these are 7 digits, but don't hard fail—just accept 6-8
            if len(digits) > 9:
                continue

            out.add(f"US{digits}{kind}")

    return out


def extract_application_id_tokens(text: str) -> Set[str]:
    s = normalize_for_matching(text)
    out: Set[str] = set()

    for m in US_APP_RE.finditer(s):
        tok = m.group(0).replace(" ", "").replace(",", "")
        out.add(tok)

    for m in PCT_APP_RE.finditer(s):
        tok = m.group(0).upper().replace(" ", "")
        out.add(tok)

    return out


def extract_ipc_tokens(text: str) -> Set[str]:
    s = normalize_for_matching(text)
    out: Set[str] = set()
    for m in IPC_RE.finditer(s):
        tok = m.group(0).replace(" ", "")
        tok = canonicalize_codeish_digits(tok)
        out.add(tok)
    return out


def extract_uscl_tokens(text: str) -> Set[str]:
    s = normalize_for_matching(text)
    out: Set[str] = set()
    for m in USCL_RE.finditer(s):
        tok = m.group(0).replace(" ", "")
        tok = canonicalize_codeish_digits(tok)
        out.add(tok)
    return out
