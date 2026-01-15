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
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedNorm[ReportedCounts]]:
    """
    New-model equivalent of extract_reported_counts(front_text).

    Returns ParsedNorm[ReportedCounts] with:
      - value: ReportedCounts(claims, drawing_sheets)
      - raw_text: matched source snippet
      - where: provenance span(s) for the snippet
    """
    linear_text, segments = linearize(doc, sep=sep, order=order)
    m = REPORTED_COUNTS_PAT.search(linear_text or "")
    if not m:
        return None

    g_start, g_end = m.span(0)
    # Keep the snippet exact (don’t trim inside it; but trimming outer whitespace is fine)
    t_start, t_end = trim_global_range(linear_text, g_start, g_end)

    snippet = linear_text[t_start:t_end]
    where = global_range_to_where(t_start, t_end, segments)

    counts = ReportedCounts(
        reported_claim_count=int(m.group(1)),
        reported_drawing_sheet_count=int(m.group(2)),
    )

    raw = ParsedRaw[str](
        kind=EntityKind.UNKNOWN,  # or introduce EntityKind.REPORTED_COUNTS if you want
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

    # Normalize into a typed value object
    return raw.normalize_to(
        value=counts,
        kind=EntityKind.UNKNOWN,  # or EntityKind.REPORTED_COUNTS
        system="PDF",
        rule="reported-counts:extract",
        normalized=True,
        reported_claim_count=counts.reported_claim_count,
        reported_drawing_sheet_count=counts.reported_drawing_sheet_count,
    )
