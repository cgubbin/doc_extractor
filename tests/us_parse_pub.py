import re
from typing import Set

from tests.normalise import normalise_for_contains

# Match US publication references where the YEAR is part of the publication number itself:
#   2005/0057747 A1
#   2005.0109729 A1
#   2005/019 1858 A1
#   2007/0293,052 A1
#   2008/01653.57 A1
#
# Critical: avoid month/year like "11/2001" by requiring year NOT preceded by digit+slash.
_USPUB_RE = re.compile(
    r"(?<!\d/)\b"  # NOT preceded by e.g. "11/"
    r"(?P<year>19\d{2}|20\d{2})"  # 4-digit year
    r"\s*[/\.]\s*"  # slash or dot separator (common OCR variants)
    r"(?P<serial>[\d\s,\.]{6,12})"  # 6–8 digits with OCR noise separators
    r"\s*(?P<kind>[A-Z0-9]\d)\b",  # kind code; allow OCR digit in letter slot (82)
    re.IGNORECASE,
)


def _fix_kind(kind: str) -> str:
    k = kind.upper().replace(" ", "")
    # Fix OCR in kind-letter position only (penultimate char)
    if len(k) == 2 and k[0].isdigit() and k[1].isdigit():
        if k[0] == "8":
            return "B" + k[1]
        if k[0] == "4":
            return "A" + k[1]
    return k


def _canon_pub_serial(serial_raw: str) -> str | None:
    digits = "".join(ch for ch in serial_raw if ch.isdigit())

    # Publication serial should be 7 digits (leading zeros allowed).
    # If OCR dropped a leading zero: pad.
    if len(digits) == 6:
        digits = "0" + digits

    # If OCR inserted a leading zero and you got 8 digits, drop *only* if the first is 0.
    if len(digits) == 8 and digits[0] == "0":
        digits = digits[1:]

    if len(digits) != 7:
        return None
    return digits


def parse_us_pub_from_ocr_fragment(text: str) -> Set[str]:
    """
    Extract canonical US publication ids from noisy OCR references.
    Canonical: US + YYYY + 7-digit serial + kind (A1/A2/B1/B2).
    """
    s = normalise_for_contains(text)
    out: Set[str] = set()

    for m in _USPUB_RE.finditer(s):
        year = m.group("year")
        serial = _canon_pub_serial(m.group("serial"))
        if not serial:
            continue
        kind = _fix_kind(m.group("kind"))
        if kind not in {"A1", "A2", "A9", "B1", "B2"}:
            continue

        out.add(f"US{year}{serial}{kind}")

    return out
