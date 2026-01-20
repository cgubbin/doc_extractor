from datetime import datetime
import re
from typing import Optional

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind, EntityKind
from patent_ingest.front_matter.util import (
    normalize_whitespace_basic,
    normalize_punctuation_spacing,
    _linear_find_group1_as_raw,
)
from patent_ingest.diagnostics import Diagnostics

# =============================================================================
# Dates
# =============================================================================

_MONTH_FIX = {
    "Jan.": "Jan",
    "Feb.": "Feb",
    "Mar.": "Mar",
    "Apr.": "Apr",
    "Jun.": "Jun",
    "Jul.": "Jul",
    "Aug.": "Aug",
    "Sep.": "Sep",
    "Sept.": "Sep",
    "Oct.": "Oct",
    "Nov.": "Nov",
    "Dec.": "Dec",
}


def remove_whitespace(s: str) -> str:
    return re.sub(r"\s*", "", (s or ""))


def parse_uspto_date_to_iso(raw: str) -> Optional[str]:
    """
    Accepts strings like "Dec. 8, 2009" or "December 8, 2009".
    Returns ISO date "2009-12-08" or None.
    """
    if not raw:
        return None
    s = normalize_whitespace_basic(raw)
    s = normalize_punctuation_spacing(s)
    for k, v in _MONTH_FIX.items():
        s = s.replace(k, v)

    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.date().isoformat()
        except ValueError:
            pass
    return None


DATE_OF_PATENT_FALLBACK_PAT = re.compile(
    r"\bDate\s+of\s+Patent\s*:\s*([A-Za-z\s*\.]+\s*\d{1,2}\s*,\s*\d{4})\b",
    re.IGNORECASE,
)

DATE_GENERIC_PAT = re.compile(r"\b([A-Za-z\.]+\s+\d{1,2},\s+\d{4})\b")


def _strip_leading_label(s: str, labels: list[str]) -> str:
    if not s:
        return s
    ss = s.lstrip()
    for lab in labels:
        if ss.lower().startswith(lab.lower()):
            cut = ss[len(lab) :]
            return cut.lstrip(" :\t\r\n")
    return s


def extract_grant_date(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    diag: Diagnostics,
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.RIGHT, Column.LEFT),
) -> Optional[ParsedNorm[str]]:
    field = "grant_date"

    inid45 = inid_blocks.get(INIDKind._45)
    if inid45 and (inid45.text or "").strip():
        clean = (
            _strip_leading_label(
                inid45.text, ["Date of Patent", "Date of Patent:", "Date of Patent :"]
            ).strip()
            or None
        )
        iso = parse_uspto_date_to_iso(clean) if clean else None
        if iso:
            raw = ParsedRaw[str](
                kind=EntityKind.DATE,
                where=inid45.where,
                text=clean,
                confidence=inid45.confidence,
                meta={**inid45.meta, "source": "inid", "inid_code": "45"},
            )
            return raw.normalize_to(
                value=iso,
                kind=EntityKind.DATE,
                system="USPTO",
                rule="grant-date:inid45",
                iso=iso,
                normalized=True,
            )

        diag.warn(
            "grant_date.inid_parse_failed",
            "INID(45) present but date parsing failed; attempting fallback.",
            field=field,
            where=inid45.where,
            raw=(inid45.text or "")[:160],
            inid="45",
        )

    fb1 = _linear_find_group1_as_raw(
        doc,
        DATE_OF_PATENT_FALLBACK_PAT,
        kind=EntityKind.DATE,
        sep=sep,
        order=order,
        confidence=0.35,
        meta={"rule": "grant-date:fallback Date of Patent:"},
    )
    if fb1 and (fb1.text or "").strip():
        clean = fb1.text.strip()
        iso = parse_uspto_date_to_iso(clean) if clean else None
        if iso:
            return fb1.normalize_to(
                value=iso,
                kind=EntityKind.DATE,
                system="USPTO",
                rule="grant-date:fallback-label",
                iso=iso,
                normalized=True,
            )
        diag.warn(
            "grant_date.fallback_label_parse_failed",
            "Found 'Date of Patent:' but the date did not parse; attempting generic date fallback.",
            field=field,
            where=fb1.where,
            raw=(fb1.text or "")[:160],
        )

    fb2 = _linear_find_group1_as_raw(
        doc,
        DATE_GENERIC_PAT,
        kind=EntityKind.DATE,
        sep=sep,
        order=order,
        confidence=0.2,
        meta={"rule": "grant-date:fallback-first-generic-date"},
    )
    if fb2 and (fb2.text or "").strip():
        clean = fb2.text.strip()
        iso = parse_uspto_date_to_iso(clean) if clean else None
        if iso:
            return fb2.normalize_to(
                value=iso,
                kind=EntityKind.DATE,
                system="USPTO",
                rule="grant-date:fallback-generic",
                iso=iso,
                normalized=True,
            )
        diag.error(
            "grant_date.generic_parse_failed",
            "Found a date-like string but parsing failed.",
            field=field,
            where=fb2.where,
            raw=(fb2.text or "")[:160],
        )
        return None

    diag.error(
        "grant_date.missing",
        "No grant date found in INID(45) or fallback.",
        field=field,
    )
    return None


FILED_FALLBACK_PAT = re.compile(
    r"\bFiled\s*:\s*([A-Za-z\s*\.]+\s*\d{1,2}\s*,\s*\d{4})\b",
    re.IGNORECASE,
)


def extract_filed_date(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    diag: Diagnostics,
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedNorm[str]]:
    field = "filed_date"

    inid22 = inid_blocks.get(INIDKind._22)
    if inid22 and (inid22.text or "").strip():
        clean = _strip_leading_label(inid22.text, ["Filed"]).strip() or None
        iso = parse_uspto_date_to_iso(clean) if clean else None
        if iso:
            raw = ParsedRaw[str](
                kind=EntityKind.DATE,
                where=inid22.where,
                text=clean,
                confidence=inid22.confidence,
                meta={**inid22.meta, "source": "inid", "inid_code": "22"},
            )
            return raw.normalize_to(
                value=iso,
                kind=EntityKind.DATE,
                system="USPTO",
                rule="filed-date:inid22",
                iso=iso,
                normalized=True,
            )

        diag.warn(
            "filed_date.inid_parse_failed",
            "INID(22) present but date parsing failed; attempting fallback.",
            field=field,
            where=inid22.where,
            raw=(inid22.text or "")[:160],
            inid="22",
        )

    fb = _linear_find_group1_as_raw(
        doc,
        FILED_FALLBACK_PAT,
        kind=EntityKind.DATE,
        sep=sep,
        order=order,
        confidence=0.35,
        meta={"rule": "filed-date:fallback Filed:"},
    )
    if fb and (fb.text or "").strip():
        clean = fb.text.strip()
        iso = parse_uspto_date_to_iso(clean) if clean else None
        if iso:
            return fb.normalize_to(
                value=iso,
                kind=EntityKind.DATE,
                system="USPTO",
                rule="filed-date:fallback",
                iso=iso,
                normalized=True,
            )

        diag.error(
            "filed_date.fallback_parse_failed",
            "Fallback matched a date-like string but parsing still failed.",
            field=field,
            where=fb.where,
            raw=(fb.text or "")[:160],
        )
        return None

    diag.error(
        "filed_date.missing",
        "No filed/submitted date found in INID(22) or fallback.",
        field=field,
    )
    return None
