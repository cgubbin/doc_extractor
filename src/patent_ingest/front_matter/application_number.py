from __future__ import annotations

import re
from typing import Any, Optional, Tuple

from patent_ingest.diagnostics import Diagnostics
from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Span, Column, Position, Where
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind, EntityKind
from patent_ingest.common import (
    strip_leading_label_with_idx,
    refine_where_by_slice,
)


# =============================================================================
# Application number + filing date + grant date (INID + fallback regex)
# =============================================================================

APPL_NO_FALLBACK_PAT = re.compile(
    r"\bAppl\s*\.\s*No\s*\.\s*:\s*([0-9]{2}\s*/\s*[0-9\s*,\s*]{3,7}[0-9]{3})\b",
    re.IGNORECASE,
)

# Headings that frequently follow (21) and can contaminate the INID slice
APPL_STOP_PAT = re.compile(
    r"\b(OTHER\s+PUBLICATIONS|U\.S\.\s*PATENT\s*DOCUMENTS|FOREIGN\s+PATENT\s*DOCUMENTS|"
    r"REFERENCES\s+CITED|ABSTRACT|Primary\s+Examiner|Assistant\s+Examiner)\b",
    re.IGNORECASE,
)

# Labels to strip if they appear at the start of the INID slice
APPL_LABELS = ["Appl. No.", "Appl No.", "Application No.", "Application No"]


# --------------------------
# Normalization + validation
# --------------------------


def normalize_us_application_no(raw: str) -> Optional[str]:
    """
    Normalize variants like '13 / 766 , 598' -> '13/766,598'
    Also fixes OCR-added leading zeros on the prefix, e.g. '016/197,849' -> '16/197,849'
    """
    if not raw:
        return None

    s = raw.upper()
    s = s.replace("O", "0")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^0-9/,]", "", s)

    if s.count("/") != 1:
        return None

    left, right = s.split("/", 1)
    if not left.isdigit():
        return None

    # Fix: OCR can add an erroneous leading '0' making prefix 3+ digits (e.g. 016/...)
    if len(left) > 2:
        left2 = left.lstrip("0")
        left = left2 if left2 else "0"

    right_digits = re.sub(r"[^0-9]", "", right)
    if not right_digits.isdigit():
        return None

    if len(right_digits) >= 6:
        main = right_digits[:-3]
        tail = right_digits[-3:]
        return f"{left}/{main},{tail}"
    else:
        return f"{left}/{right_digits}"


def validate_us_application_no_text(text: str) -> bool:
    """
    Treat as valid if normalization succeeds OR if it matches the fallback pattern somewhere.
    """
    s = " ".join((text or "").split())
    if normalize_us_application_no(s):
        return True
    return bool(APPL_NO_FALLBACK_PAT.search(s))


# --------------------------
# Text cleaning with span refinement
# --------------------------


def _cut_at_heading_with_idx(s: str, stop_pat: re.Pattern[str]) -> Tuple[str, int]:
    """
    Cut string at first stop heading match. Returns (cut_text, end_index_in_original).
    If no heading, end_index = len(s).
    """
    m = stop_pat.search(s or "")
    if not m:
        return s, len(s)
    return s[: m.start()], m.start()


def _clean_application_slice(raw: ParsedRaw[str]) -> ParsedRaw[str]:
    """
    Apply:
      - strip leading label
      - cut at heading
      - whitespace trim
    And attempt to refine the span if possible.
    """
    original = raw.text or ""
    s = original

    # 1) strip label
    s1, strip_idx = strip_leading_label_with_idx(s, APPL_LABELS)

    # 2) cut at heading
    s2, cut_end_rel = _cut_at_heading_with_idx(s1, APPL_STOP_PAT)

    # 3) final trim
    s3 = s2.strip()

    # Map trimming back to indices in s2
    # Compute trim offsets relative to s2
    left_trim = len(s2) - len(s2.lstrip())
    right_trim = len(s2.rstrip())

    # Compute overall slice indices relative to original string
    # original -> (strip label) -> s1, so s1 corresponds to original[strip_idx:]
    start_idx = strip_idx + left_trim
    end_idx = strip_idx + right_trim  # right_trim is length of rstripped s2

    # If we cut early, right_trim should not exceed cut_end_rel
    end_idx = min(end_idx, strip_idx + cut_end_rel)

    # If after cleaning it became empty, just return with empty text (no refinement needed)
    if not s3:
        return raw.with_text("", cleaned=True)

    where2, refine_meta = refine_where_by_slice(raw, start_idx, end_idx)
    return ParsedRaw[str](
        kind=raw.kind,
        where=where2,
        text=s3,
        confidence=raw.confidence,
        meta={**raw.meta, **refine_meta, "cleaned": True},
    )


# --------------------------
# Fallback search in the document region
# --------------------------


def find_first_application_no_fallback(doc: MultiPage) -> Optional[ParsedRaw[str]]:
    """
    Your stated heuristic: “first suitable substring in the second column of the first page”.
    This uses the APPL_NO_FALLBACK_PAT capturing group and returns that group as the span/text.
    """
    text = doc.get_column_text(page=0, column=Column.LEFT)
    m = APPL_NO_FALLBACK_PAT.search(text or "")
    if not m:
        return None

    start, end = m.span(1)
    where = Span(
        start=Position(page=0, column=Column.LEFT, offset=start),
        end=Position(page=0, column=Column.LEFT, offset=end),
    )
    return ParsedRaw[str](
        kind=EntityKind.APPLICATION_ID,
        where=where,
        text=text[start:end].strip(),
        confidence=0.35,
        meta={
            "source": "fallback",
            "rule": "appl-no:first-match page0/right",
            "pattern": APPL_NO_FALLBACK_PAT.pattern,
        },
    )


# --------------------------
# Main extractor: INID if valid, else fallback
# --------------------------


def extract_application_number(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    diag: Diagnostics,
) -> Optional[ParsedNorm[str]]:
    field = "application_number"

    inid21 = inid_blocks.get(INIDKind._21)
    if inid21 and (inid21.text or "").strip():
        tagged = inid21.retag(
            EntityKind.APPLICATION_ID,
            rule="appl-no:retag inid21",
            source="inid",
            inid_code="21",
        )
        cleaned = _clean_application_slice(tagged)

        if cleaned.text and validate_us_application_no_text(cleaned.text):
            norm = normalize_us_application_no(cleaned.text)
            value = norm or cleaned.text
            if norm is None:
                diag.warn(
                    "appl_no.un_normalized",
                    "INID(21) looked like an application number but normalization failed; returning cleaned text.",
                    field=field,
                    where=cleaned.where,
                    raw=cleaned.text[:160],
                    inid="21",
                )
            return cleaned.normalize_to(
                value=value,
                kind=EntityKind.APPLICATION_ID,
                system="USPTO",
                rule="appl-no:inid21",
                normalized=bool(norm),
                normalized_value=norm,
                source="inid",
                inid_code="21",
            )

        diag.warn(
            "appl_no.inid_invalid",
            "INID(21) present but not a valid US application number; attempting fallback.",
            field=field,
            where=inid21.where,
            raw=(inid21.text or "")[:160],
            inid="21",
        )

    fb = find_first_application_no_fallback(doc)
    if fb:
        cleaned_fb = _clean_application_slice(fb)
        if cleaned_fb.text and validate_us_application_no_text(cleaned_fb.text):
            norm = normalize_us_application_no(cleaned_fb.text)
            value = norm or cleaned_fb.text
            if norm is None:
                diag.warn(
                    "appl_no.fallback_un_normalized",
                    "Fallback found an application number but normalization failed; returning cleaned text.",
                    field=field,
                    where=cleaned_fb.where,
                    raw=cleaned_fb.text[:160],
                )
            return cleaned_fb.normalize_to(
                value=value,
                kind=EntityKind.APPLICATION_ID,
                system="USPTO",
                rule="appl-no:fallback",
                normalized=bool(norm),
                normalized_value=norm,
                source="fallback",
            )

        diag.error(
            "appl_no.fallback_invalid",
            "Fallback matched, but the captured value is not a valid US application number.",
            field=field,
            where=fb.where,
            raw=(fb.text or "")[:160],
        )
        return None

    diag.error(
        "appl_no.missing",
        "No application number found in INID(21) or fallback.",
        field=field,
    )
    return None
