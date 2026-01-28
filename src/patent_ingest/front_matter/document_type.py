"""
Patent document type detection and type-specific field handling.

Document types have different expected fields and formats:

GRANTED:
  - Has INID(45) grant date
  - Patent number format: US1234567B2
  - Has claim/drawing counts
  - All standard fields expected

PUBLISHED_APPLICATION (non-PCT):
  - Publication number format: US...A1
  - Has INID(22) filed date
  - Has INID(21) application number
  - NO grant date
  - Has claim/drawing counts (usually)

PCT_APPLICATION:
  - Has INID(86) with PCT info
  - Publication format: US...A1
  - PCT NO. in INID(86) -> application_number
  - PCT Filed in INID(86) -> filed_date
  - S371(c) date -> US entry date (separate field)
  - NO claim/drawing counts in front matter
  - May have INID(45) with publication date (not grant date)

PROVISIONAL:
  - Application number format: 61/... or 62/...
  - Very minimal front matter
  - NO abstract typically
  - NO claim/drawing counts
"""

import re
from enum import Enum
from typing import Optional
from dataclasses import dataclass

from patent_ingest.model.document import MultiPage
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind, EntityKind
from patent_ingest.diagnostics import Diagnostics
from patent_ingest.front_matter.grant_date import parse_uspto_date_to_iso


class DocumentType(str, Enum):
    """Patent document type based on content and format."""
    GRANTED = "granted"
    PUBLISHED_APPLICATION = "published_application"
    PCT_APPLICATION = "pct_application"
    PROVISIONAL = "provisional"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DocumentTypeInfo:
    """Information about the document type."""
    doc_type: DocumentType
    confidence: float
    indicators: dict[str, bool]


def detect_document_type(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    patent_id: Optional[ParsedNorm] = None,
) -> DocumentTypeInfo:
    """
    Detect document type based on INID blocks and patent ID format.

    Order of detection:
    1. Provisional (61/... or 62/... application number)
    2. PCT (INID 86 present)
    3. Granted (patent number B1/B2 format, or INID 45 present)
    4. Published Application (patent number A1/A2 format)
    """
    indicators = {}

    # Check patent ID format
    has_grant_kind = False
    has_pub_kind = False
    if patent_id and patent_id.value:
        pid_str = str(patent_id.value)
        has_grant_kind = bool(re.search(r"\b[B-C]\d\b", pid_str))  # B1, B2, C1, etc.
        has_pub_kind = bool(re.search(r"\bA[1-3]\b", pid_str))  # A1, A2, A3

    indicators["has_grant_kind_code"] = has_grant_kind
    indicators["has_pub_kind_code"] = has_pub_kind

    # Check for provisional application number (61/... or 62/...)
    inid_21 = inid_blocks.get(INIDKind._21)
    is_provisional = False
    if inid_21 and inid_21.text:
        is_provisional = bool(re.search(r"\b6[12]/", inid_21.text))
    indicators["has_provisional_app_no"] = is_provisional

    # Check for PCT indicators
    has_pct_inid = INIDKind._86 in inid_blocks
    has_pct_number = False
    has_s371 = False
    if has_pct_inid:
        inid_86_text = inid_blocks[INIDKind._86].text or ""
        has_pct_number = bool(re.search(r"PCT\s*(?:NO\.?|/)", inid_86_text, re.IGNORECASE))
        has_s371 = bool(re.search(r"S\s*371\s*\(c\)", inid_86_text, re.IGNORECASE))

    indicators["has_pct_inid_86"] = has_pct_inid
    indicators["has_pct_number"] = has_pct_number
    indicators["has_s371_date"] = has_s371

    # Check for grant date (INID 45)
    has_grant_date = INIDKind._45 in inid_blocks
    indicators["has_grant_date_inid"] = has_grant_date

    # Determine document type
    if is_provisional:
        return DocumentTypeInfo(
            doc_type=DocumentType.PROVISIONAL,
            confidence=0.95,
            indicators=indicators,
        )

    if has_pct_inid and (has_pct_number or has_s371):
        return DocumentTypeInfo(
            doc_type=DocumentType.PCT_APPLICATION,
            confidence=0.9,
            indicators=indicators,
        )

    if has_grant_kind or has_grant_date:
        return DocumentTypeInfo(
            doc_type=DocumentType.GRANTED,
            confidence=0.85,
            indicators=indicators,
        )

    if has_pub_kind:
        return DocumentTypeInfo(
            doc_type=DocumentType.PUBLISHED_APPLICATION,
            confidence=0.8,
            indicators=indicators,
        )

    # Default to unknown
    return DocumentTypeInfo(
        doc_type=DocumentType.UNKNOWN,
        confidence=0.3,
        indicators=indicators,
    )


# PCT-specific extractors

PCT_NUMBER_PAT = re.compile(
    r"PCT\s*/\s*([A-Z]{2})\s*(\d{2,4})\s*/\s*(\d+)",
    re.IGNORECASE,
)


def extract_pct_application_number(
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    diag: Diagnostics,
) -> Optional[ParsedNorm[str]]:
    """
    Extract PCT application number from INID(86) block.

    Format: PCT/US08/54913 or PCT/US2008/054913
    Returns normalized form: PCT/US08/54913
    """
    field = "application_number"

    inid_86 = inid_blocks.get(INIDKind._86)
    if not inid_86 or not inid_86.text:
        diag.warn(
            "pct.application_number_missing",
            "PCT application but no INID(86) block found.",
            field=field,
        )
        return None

    m = PCT_NUMBER_PAT.search(inid_86.text)
    if not m:
        diag.warn(
            "pct.application_number_not_found",
            "PCT INID(86) present but no PCT number found.",
            field=field,
            where=inid_86.where,
            raw=(inid_86.text or "")[:200],
        )
        return None

    country = m.group(1).upper()
    year = m.group(2)
    number = m.group(3)

    # Standardize to short year format
    if len(year) == 4:
        year = year[-2:]  # 2008 -> 08

    normalized = f"PCT/{country}{year}/{number}"

    raw = ParsedRaw[str](
        kind=EntityKind.APPLICATION_ID,
        where=inid_86.where,
        text=m.group(0),
        confidence=0.7,
        meta={
            **inid_86.meta,
            "source": "pct",
            "inid_code": "86",
            "pct_country": country,
            "pct_year": year,
            "pct_number": number,
        },
    )

    return raw.normalize_to(
        value=normalized,
        kind=EntityKind.APPLICATION_ID,
        system="PCT",
        rule="pct:application-number",
        normalized=True,
        pct_country=country,
        pct_year=year,
        pct_number=number,
    )


PCT_FILED_PAT = re.compile(
    r"PCT\s+Fl?ed\s*:\s*([A-Za-z\s*\.]+\s*\d{1,2}\s*,\s*\d{4})",
    re.IGNORECASE,
)


def extract_pct_filed_date(
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    diag: Diagnostics,
) -> Optional[ParsedNorm[str]]:
    """
    Extract PCT filing date from INID(86) block.

    Label: "PCT Filed:" or "PCT Fled:" (typo in some PDFs)
    """
    field = "filed_date"

    inid_86 = inid_blocks.get(INIDKind._86)
    if not inid_86 or not inid_86.text:
        diag.warn(
            "pct.filed_date_missing",
            "PCT application but no INID(86) block found.",
            field=field,
        )
        return None

    m = PCT_FILED_PAT.search(inid_86.text)
    if not m:
        diag.warn(
            "pct.filed_date_not_found",
            "PCT INID(86) present but no PCT filed date found.",
            field=field,
            where=inid_86.where,
            raw=(inid_86.text or "")[:200],
        )
        return None

    date_str = m.group(1)
    iso = parse_uspto_date_to_iso(date_str)

    if not iso:
        diag.error(
            "pct.filed_date_parse_failed",
            f"PCT filed date found but failed to parse: {date_str}",
            field=field,
            where=inid_86.where,
            raw=date_str,
        )
        return None

    raw = ParsedRaw[str](
        kind=EntityKind.DATE,
        where=inid_86.where,
        text=date_str,
        confidence=0.7,
        meta={
            **inid_86.meta,
            "source": "pct",
            "inid_code": "86",
            "label": "PCT Filed",
        },
    )

    return raw.normalize_to(
        value=iso,
        kind=EntityKind.DATE,
        system="PCT",
        rule="pct:filed-date",
        normalized=True,
        iso=iso,
    )


S371_DATE_PAT = re.compile(
    r"S\s*371\s*\(c\)\s*\(\s*\d+\s*\)\s*,?\s*\(\s*\d+\s*\)\s*,?\s*\(\s*\d+\s*\)\s+Date\s*:\s*([A-Za-z\s*\.]+\s*\d{1,2}\s*,\s*\d{4})",
    re.IGNORECASE | re.DOTALL,
)


def extract_s371_date(
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    diag: Diagnostics,
) -> Optional[ParsedNorm[str]]:
    """
    Extract S371(c) date - the US national stage entry date.

    This is separate from both the PCT filing date and any publication date.
    """
    inid_86 = inid_blocks.get(INIDKind._86)
    if not inid_86 or not inid_86.text:
        return None

    m = S371_DATE_PAT.search(inid_86.text)
    if not m:
        return None

    date_str = m.group(1)
    iso = parse_uspto_date_to_iso(date_str)

    if not iso:
        return None

    raw = ParsedRaw[str](
        kind=EntityKind.DATE,
        where=inid_86.where,
        text=date_str,
        confidence=0.6,
        meta={
            **inid_86.meta,
            "source": "pct",
            "inid_code": "86",
            "label": "S371(c) US Entry",
        },
    )

    return raw.normalize_to(
        value=iso,
        kind=EntityKind.DATE,
        system="PCT",
        rule="pct:s371-entry-date",
        normalized=True,
        iso=iso,
    )
