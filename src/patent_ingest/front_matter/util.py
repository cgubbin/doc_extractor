from patent_ingest.model.span import Column, Span, Position
from patent_ingest.model.mapping import (
    linearize,
    trim_global_range,
    global_range_to_where,
)
from patent_ingest.model.document import MultiPage
from patent_ingest.parsed import Kind, ParsedRaw

# Re-export from common for backwards compatibility
from patent_ingest.common import (
    normalize_whitespace,
    normalize_whitespace_basic,
    normalize_punctuation_spacing,
    normalize_text_field,
    dehyphenate,
    strip_front_page_noise,
)

import re
from typing import Optional, Any


def find_first_in_region(
    doc: MultiPage,
    *,
    page: int,
    column: Column,
    pat: re.Pattern[str],
    kind: Kind,
    confidence: float | None = 0.4,
    trim: bool = True,
    meta: dict[str, Any] | None = None,
) -> Optional[ParsedRaw[str]]:
    text = doc.get_column_text(page, column)
    m = pat.search(text)
    if not m:
        return None

    start, end = m.span()

    if trim:
        # Trim within region (column text), not global
        s, e = start, end
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        start, end = s, e

    where = Span(
        start=Position(page=page, column=column, offset=start),
        end=Position(page=page, column=column, offset=end),
    )

    out_meta = dict(meta or {})
    out_meta.update(
        {
            "fallback_region": {"page": page, "column": column.value},
            "match_span": (m.start(), m.end()),
            "pattern": pat.pattern,
        }
    )

    return ParsedRaw[str](
        kind=kind,
        where=where,
        text=text[start:end],
        confidence=confidence,
        meta=out_meta,
    )


def normalize_us_application_no(raw: str) -> Optional[str]:
    """
    Normalize variants like '13 / 766 , 598' -> '13/766,598'
    """
    if not raw:
        return None

    s = raw.upper()
    s = s.replace("O", "0")  # defensive; sometimes O->0 issues happen
    s = re.sub(r"\s+", "", s)

    # Keep only digits, slash, comma
    s = re.sub(r"[^0-9/,]", "", s)

    # Must contain exactly one slash with digits on both sides
    if s.count("/") != 1:
        return None
    left, right = s.split("/", 1)
    if not left.isdigit():
        return None

    # Remove commas from right side then reinsert properly if long enough
    right_digits = re.sub(r"[^0-9]", "", right)
    if not right_digits.isdigit():
        return None

    # Typical: 6 digits -> XXX,XXX ; sometimes 7+ exist; keep last 6 grouped
    if len(right_digits) >= 6:
        main = right_digits[:-3]
        tail = right_digits[-3:]
        return f"{left}/{main},{tail}"
    else:
        # Keep as-is (rare)
        return f"{left}/{right_digits}"


def _linear_find_group1_as_raw(
    doc: MultiPage,
    pat: re.Pattern[str],
    *,
    kind: Kind,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
    confidence: float | None = 0.35,
    meta: dict[str, Any] | None = None,
) -> Optional[ParsedRaw[str]]:
    """
    Search linearized doc for pat, return group(1) as ParsedRaw with mapped Where.
    """
    linear_text, segments = linearize(doc, sep=sep, order=order)
    m = pat.search(linear_text)
    if not m:
        return None
    g_start, g_end = m.span(1)
    g_start, g_end = trim_global_range(linear_text, g_start, g_end)

    where = global_range_to_where(g_start, g_end, segments)
    out_meta = dict(meta or {})
    out_meta.update(
        {
            "global": (g_start, g_end),
            "pattern": pat.pattern,
            "source": "fallback",
        }
    )

    return ParsedRaw[str](
        kind=kind,
        where=where,
        text=linear_text[g_start:g_end],
        confidence=confidence,
        meta=out_meta,
    )


def _linear_find_group0_as_raw(
    doc: MultiPage,
    pat: re.Pattern[str],
    *,
    kind: Kind,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
    confidence: float | None = 0.25,
    meta: dict[str, Any] | None = None,
) -> Optional[ParsedRaw[str]]:
    """
    Search linearized doc for pat, return group(0) as ParsedRaw with mapped Where.
    """
    linear_text, segments = linearize(doc, sep=sep, order=order)
    m = pat.search(linear_text)
    if not m:
        return None
    g_start, g_end = m.span(0)
    g_start, g_end = trim_global_range(linear_text, g_start, g_end)

    where = global_range_to_where(g_start, g_end, segments)
    out_meta = dict(meta or {})
    out_meta.update(
        {
            "global": (g_start, g_end),
            "pattern": pat.pattern,
            "source": "fallback",
        }
    )

    return ParsedRaw[str](
        kind=kind,
        where=where,
        text=linear_text[g_start:g_end],
        confidence=confidence,
        meta=out_meta,
    )
