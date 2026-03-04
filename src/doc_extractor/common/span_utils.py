"""Span manipulation and text cleaning utilities with provenance tracking.

This module contains functions for manipulating text spans while preserving
location information for extracted patent data.
"""

import re
from typing import Any, Sequence

from doc_extractor.model.span import Span, Position, Where
from doc_extractor.parsed import ParsedRaw


def cut_at_earliest_with_idx(
    s: str, patterns: Sequence[re.Pattern[str]]
) -> tuple[str, int]:
    """Cut string at first occurrence of any stop pattern.

    Returns the text up to the first match and the end index in the original string.
    If no pattern matches, returns the stripped string and len(s).

    Args:
        s: Input string
        patterns: Sequence of regex patterns to search for (stop markers)

    Returns:
        Tuple of (cut_text, end_index_in_original_s)
    """
    if not s:
        return s, 0
    stops: list[int] = []
    for pat in patterns:
        m = pat.search(s)
        if m:
            stops.append(m.start())
    if not stops:
        return s.strip(), len(s)
    end = min(stops)
    return s[:end].strip(), end


def strip_leading_label_with_idx(s: str, labels: list[str]) -> tuple[str, int]:
    """Strip a leading label from text and return the start index.

    Case-insensitive label matching. Strips the label and any following
    whitespace or colons.

    Args:
        s: Input string with potential leading label
        labels: List of possible label strings to strip

    Returns:
        Tuple of (new_string_without_label, start_index_in_original)
    """
    if not s:
        return s, 0

    lead_ws = len(s) - len(s.lstrip())
    ss = s.lstrip()

    for lab in labels:
        if ss.lower().startswith(lab.lower()):
            cut = ss[len(lab) :]
            cut2 = cut.lstrip(" :\t\r\n")
            start_idx = lead_ws + len(lab) + (len(cut) - len(cut2))
            return cut2, start_idx

    return s, 0


def refine_where_by_slice(
    raw: ParsedRaw[str], start_idx: int, end_idx: int
) -> tuple[Where, dict[str, Any]]:
    """Refine span location based on substring indices.

    If the original span is a simple Span, creates a refined Span for the
    substring raw.text[start_idx:end_idx]. If it's a MultiSpan, keeps it
    as-is and records the indices in metadata.

    Args:
        raw: Original ParsedRaw object with location information
        start_idx: Start index of substring in raw.text
        end_idx: End index of substring in raw.text

    Returns:
        Tuple of (refined_where, metadata_dict)
    """
    meta: dict[str, Any] = {"refine": {"start_idx": start_idx, "end_idx": end_idx}}

    if isinstance(raw.where, Span):
        new_start = Position(
            raw.where.start.page,
            raw.where.start.column,
            raw.where.start.offset + start_idx,
        )
        new_end = Position(
            raw.where.end.page, raw.where.end.column, raw.where.start.offset + end_idx
        )
        return Span(new_start, new_end), meta

    return raw.where, meta
