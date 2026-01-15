from datetime import datetime
import re
from typing import Any, Optional

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind, EntityKind
from patent_ingest.front_matter.util import (
    normalize_whitespace_basic,
    normalize_punctuation_spacing,
    _linear_find_group1_as_raw,
)

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
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.RIGHT, Column.LEFT),
) -> ParsedNorm[str]:
    """
    New-model equivalent of your old extract_grant_date().

    Returns ParsedNorm[str]:
      - kind: EntityKind.DATE (or keep as INID(45) if you prefer)
      - raw_text: cleaned human date (e.g., "Jan. 2, 2020")
      - value: same as raw_text (string); ISO is stored in meta["iso"]
      - where: Where into the original doc (Span or MultiSpan)
    Raises TypeError if nothing found (same behavior as your previous code).
    """
    rejections: list[dict[str, Any]] = []

    # --------
    # 1) INID (45)
    # --------
    inid45 = inid_blocks.get(INIDKind._45) if hasattr(INIDKind, "_45") else None
    if inid45 and (inid45.text or "").strip():
        clean = (
            _strip_leading_label(
                inid45.text,
                ["Date of Patent", "Date of Patent:", "Date of Patent :"],
            ).strip()
            or None
        )

        iso = parse_uspto_date_to_iso(clean) if clean else None
        if iso:
            # retag to a semantic entity
            as_date = inid45.retag(
                EntityKind.DATE,
                rule="grant-date:from-inid45",
                source="inid",
                inid_code="45",
            )
            # keep cleaned text as the "raw_text" provenance used for normalization
            as_date_clean = ParsedRaw[str](
                kind=as_date.kind,
                where=as_date.where,
                text=clean,
                confidence=as_date.confidence,
                meta={**as_date.meta, "rejections": rejections},
            )
            return as_date_clean.normalize_to(
                value=iso,  # human-readable value
                kind=EntityKind.DATE,
                system="USPTO",
                rule="grant-date:inid45",
                iso=iso,
                normalized=True,
            )

        rejections.append(
            {
                "source": "inid",
                "inid_code": "45",
                "reason": "parse_uspto_date_to_iso failed",
                "sample": inid45.excerpt(120),
            }
        )

    # --------
    # 2) Fallback: explicit "Date of Patent:" label
    # --------
    fb1 = _linear_find_group1_as_raw(
        doc,
        DATE_OF_PATENT_FALLBACK_PAT,
        kind=EntityKind.DATE,
        sep=sep,
        order=order,
        confidence=0.35,
        meta={"rule": "grant-date:fallback Date of Patent:", "rejections": rejections},
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
        rejections.append(
            {
                "source": "fallback",
                "reason": "label match found but ISO parse failed",
                "sample": fb1.excerpt(120),
            }
        )

    # --------
    # 3) Fallback: first generic date in the doc front text
    # --------
    fb2 = _linear_find_group1_as_raw(
        doc,
        DATE_GENERIC_PAT,
        kind=EntityKind.DATE,
        sep=sep,
        order=order,
        confidence=0.2,
        meta={
            "rule": "grant-date:fallback-first-generic-date",
            "rejections": rejections,
        },
    )
    if fb2 and (fb2.text or "").strip():
        clean = fb2.text.strip()
        iso = parse_uspto_date_to_iso(clean) if clean else None
        # In your old logic, you returned even if iso is None. We’ll keep that behavior,
        # but mark normalized=False when iso missing.
        return fb2.normalize_to(
            value=iso,
            kind=EntityKind.DATE,
            system="USPTO",
            rule="grant-date:fallback-generic",
            iso=iso,
            normalized=bool(iso),
        )

    raise TypeError("No grant date found")


FILED_FALLBACK_PAT = re.compile(
    r"\bFiled\s*:\s*([A-Za-z\s*\.]+\s*\d{1,2}\s*,\s*\d{4})\b",
    re.IGNORECASE,
)


def extract_filed_date(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedNorm[str]]:
    """
    New-model equivalent of extract_filed_date().

    Priority:
      1) INID (22) if present and parseable
      2) Fallback: explicit "Filed:" label in front text

    Returns ParsedNorm[str] or None if nothing found.
    """
    rejections: list[dict[str, Any]] = []

    # ----------------
    # 1) INID (22)
    # ----------------
    inid22 = inid_blocks.get(INIDKind._22) if hasattr(INIDKind, "_22") else None
    if inid22 and (inid22.text or "").strip():
        clean = _strip_leading_label(inid22.text, ["Filed"]).strip() or None
        iso = parse_uspto_date_to_iso(clean) if clean else None

        if iso:
            as_date = inid22.retag(
                EntityKind.DATE,
                rule="filed-date:from-inid22",
                source="inid",
                inid_code="22",
            )
            cleaned = ParsedRaw[str](
                kind=as_date.kind,
                where=as_date.where,
                text=clean,
                confidence=as_date.confidence,
                meta={**as_date.meta, "rejections": rejections},
            )
            return cleaned.normalize_to(
                value=iso,
                kind=EntityKind.DATE,
                system="USPTO",
                rule="filed-date:inid22",
                iso=iso,
                normalized=True,
            )

        rejections.append(
            {
                "source": "inid",
                "inid_code": "22",
                "reason": "parse_uspto_date_to_iso failed",
                "sample": inid22.excerpt(120),
            }
        )

    # ----------------
    # 2) Fallback: "Filed:" label
    # ----------------
    fb = _linear_find_group1_as_raw(
        doc,
        FILED_FALLBACK_PAT,
        kind=EntityKind.DATE,
        sep=sep,
        order=order,
        confidence=0.35,
        meta={"rule": "filed-date:fallback Filed:", "rejections": rejections},
    )

    if not fb or not (fb.text or "").strip():
        return None

    clean = fb.text.strip()
    iso = parse_uspto_date_to_iso(clean) if clean else None

    return fb.normalize_to(
        value=iso,
        kind=EntityKind.DATE,
        system="USPTO",
        rule="filed-date:fallback",
        iso=iso,
        normalized=bool(iso),
    )
