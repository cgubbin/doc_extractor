from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.parsed import ParsedNorm, ParsedRaw, EntityKind
from patent_ingest.model.mapping import (
    linearize,
    trim_global_range,
    global_range_to_where,
)
from patent_ingest.front_matter.counts import REPORTED_COUNTS_PAT
from patent_ingest.diagnostics import Diagnostics
from patent_ingest.front_matter.util import (
    normalize_whitespace,
    normalize_punctuation_spacing,
)

import re
from typing import Optional

ABSTRACT_HEAD_PAT = re.compile(
    r"\(\s*57\s*\)\s*ABSTRACT\b|^\s*ABSTRACT\b",
    re.IGNORECASE | re.MULTILINE,
)


def extract_abstract(
    doc: MultiPage,
    diag: Diagnostics,
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedNorm[str]]:
    """
    Same behavior as your original extract_abstract(), but with Diagnostics added.

    - Finds abstract heading "(57) ABSTRACT" or "ABSTRACT" at start of a line.
    - Abstract starts at end of the heading match (heading excluded).
    - Abstract ends at reported-counts line if present after the heading, else end of linearized text.
    - Returns ParsedNorm[str] where value is the abstract text and where is its provenance span(s).

    Diagnostics:
      - WARN when heading is missing
      - WARN when heading exists but extracted body is empty after trimming
    """
    field = "abstract"

    linear_text, segments = linearize(doc, sep=sep, order=order)

    hm = ABSTRACT_HEAD_PAT.search(linear_text or "")
    if not hm:
        diag.warn(
            "abstract.missing_heading",
            "No ABSTRACT heading found.",
            field=field,
        )
        return None

    abs_start = hm.end()
    abs_end = len(linear_text)

    cm = REPORTED_COUNTS_PAT.search(linear_text or "")
    if cm and cm.start() > hm.start():
        abs_end = cm.start()

    # Trim abstract body span to match value
    t_start, t_end = trim_global_range(linear_text, abs_start, abs_end)

    if t_end <= t_start:
        diag.warn(
            "abstract.empty",
            "ABSTRACT heading found but extracted abstract body is empty after trimming.",
            field=field,
            where=global_range_to_where(hm.start(), hm.end(), segments),
            raw=linear_text[hm.start() : hm.end()],
            meta={
                "heading_global": (hm.start(), hm.end()),
                "body_global": (t_start, t_end),
            },
        )
        return None

    value = linear_text[t_start:t_end].strip()

    # Map heading + body to Where objects
    heading_where = global_range_to_where(hm.start(), hm.end(), segments)
    body_where = global_range_to_where(t_start, t_end, segments)

    raw = ParsedRaw[str](
        kind=EntityKind.ABSTRACT,
        where=body_where,
        text=value,
        confidence=0.6,
        meta={
            "source": "regex",
            "rule": "abstract:heading-to-counts",
            "heading_global": (hm.start(), hm.end()),
            "body_global": (t_start, t_end),
        },
    )

    normalized = normalize_punctuation_spacing(normalize_whitespace(value))

    return raw.normalize_to(
        value=normalized,
        kind=EntityKind.ABSTRACT,
        system="PDF",
        rule="abstract:extract",
        normalized=True,
        heading_where=heading_where,
    )
