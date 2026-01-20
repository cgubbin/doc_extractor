import re
from dataclasses import dataclass
from typing import Optional

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.model.mapping import (
    linearize,
    trim_global_range,
    global_range_to_where,
)
from patent_ingest.parsed import ParsedNorm, ParsedRaw, EntityKind
from patent_ingest.diagnostics import Diagnostics


@dataclass(frozen=True)
class ReportedCounts:
    reported_claim_count: int
    reported_drawing_sheet_count: int


REPORTED_COUNTS_PAT = re.compile(
    r"\b(\d+)\s+Claims?\s*,\s*(\d+)\s+Drawing\s+Sheets?\b",
    re.IGNORECASE,
)


def extract_reported_counts(
    doc: MultiPage,
    diag: Diagnostics,
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedNorm[ReportedCounts]]:
    """
    Same behavior as your original extract_reported_counts(), but with Diagnostics added.

    Returns ParsedNorm[ReportedCounts] with:
      - value: ReportedCounts(claims, drawing_sheets)
      - raw_text: matched source snippet
      - where: provenance span(s) for the snippet

    Diagnostics:
      - WARN when counts line missing
      - ERROR when regex matched but integers cannot be parsed (should be rare)
    """
    field = "reported_counts"

    linear_text, segments = linearize(doc, sep=sep, order=order)
    m = REPORTED_COUNTS_PAT.search(linear_text or "")
    if not m:
        diag.warn(
            "reported_counts.missing",
            "No reported counts line found (Claims, Drawing Sheets).",
            field=field,
        )
        return None

    g_start, g_end = m.span(0)
    # Keep the snippet exact (trim outer whitespace only)
    t_start, t_end = trim_global_range(linear_text, g_start, g_end)

    snippet = linear_text[t_start:t_end]
    where = global_range_to_where(t_start, t_end, segments)

    try:
        counts = ReportedCounts(
            reported_claim_count=int(m.group(1)),
            reported_drawing_sheet_count=int(m.group(2)),
        )
    except Exception:
        diag.error(
            "reported_counts.parse_failed",
            "Reported counts matched but failed to parse integer groups.",
            field=field,
            where=where,
            raw=m.group(0),
        )
        return None

    raw = ParsedRaw[str](
        kind=EntityKind.UNKNOWN,  # or EntityKind.REPORTED_COUNTS
        where=where,
        text=snippet,
        confidence=0.6,
        meta={
            "source": "regex",
            "rule": "reported-counts:claims-and-drawings",
            "global": (t_start, t_end),
            "pattern": REPORTED_COUNTS_PAT.pattern,
        },
    )

    return raw.normalize_to(
        value=counts,
        kind=EntityKind.UNKNOWN,  # or EntityKind.REPORTED_COUNTS
        system="PDF",
        rule="reported-counts:extract",
        normalized=True,
        reported_claim_count=counts.reported_claim_count,
        reported_drawing_sheet_count=counts.reported_drawing_sheet_count,
    )
