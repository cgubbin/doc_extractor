"""Shared regex patterns used across patent parsing modules.

This module consolidates regex patterns that were previously duplicated across
body parsing, drawing sheets, and front matter extraction modules.
"""

import re


# =============================================================================
# Figure reference patterns
# =============================================================================

# Match "Fig", "Fig.", "FIG", "FIG." as standalone tokens
FIG_TOKEN_RE = re.compile(r"^(?:Fig\.?|FIG\.?)$", re.IGNORECASE)

# Match just "Fig" (case-insensitive)
FIG_WORD_RE = re.compile(r"^Fig$", re.IGNORECASE)

# Match combined figure labels like "Fig.3A", "FIG.2B"
FIG_COMBINED_RE = re.compile(
    r"^(?:Fig\.?|FIG\.?)([0-9]+[A-Za-z]?)$", re.IGNORECASE
)

# Match figure numbers like "3", "3A", "2B"
FIG_NUM_RE = re.compile(r"^([0-9]+[A-Za-z]?)$")

# Parse figure ID into number and optional suffix: "3A" -> (3, "A")
FIG_ID_RE = re.compile(r"^(\d+)([A-Za-z])?$")

# Match figure references in body text: "FIG. 2", "FIGS. 2-5", "FIGS. 1, 2 and 3"
# Captures the figure list in named group 'figlist'
FIG_REF_RE = re.compile(
    r"\bFIGS?\.?\s+"
    r"(?P<figlist>"
    r"(?:\d+[A-Z]?)"
    r"(?:\s*[-–]\s*\d+[A-Z]?)?"
    r"(?:\s*(?:,|and)\s*\d+[A-Z]?)*"
    r")",
    re.IGNORECASE,
)


# =============================================================================
# Drawing sheet patterns
# =============================================================================

# Match "Sheet X of Y" markers
SHEET_OF_RE = re.compile(
    r"\bSheet\s+([0-9A-Za-z]+)\s+of\s+([0-9]+)\b", re.IGNORECASE
)


# =============================================================================
# Front matter stop patterns
# =============================================================================

# INID (57) ABSTRACT heading
ABSTRACT_HEADING_RE = re.compile(r"\(\s*57\s*\)\s*ABSTRACT\b", re.IGNORECASE)

# References Cited heading (various forms)
REFERENCES_CITED_RE = re.compile(
    r"\bREFERENCES?\s+CITED\b", re.IGNORECASE
)

# Examiner names (primary/assistant examiner)
EXAMINER_RE = re.compile(
    r"\b(?:Primary|Assistant)\s+Examiner\s*[—:-]", re.IGNORECASE
)

# Generic "Examiner:" label
EXAMINER_LABEL_RE = re.compile(r"\bExaminer\s*:", re.IGNORECASE)


# =============================================================================
# Date patterns
# =============================================================================

# Full date pattern: "Dec. 8, 2009" or "October 15, 2020"
FULL_DATE_RE = re.compile(
    r"\b([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(\d{4})\b"
)

# ISO date: "2009-12-08"
ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


# =============================================================================
# Application number patterns
# =============================================================================

# US application number: "13/766,598" or "13 / 766 , 598"
APPLICATION_NUMBER_RE = re.compile(
    r"\b(\d{1,2})\s*/\s*(\d{3})\s*,?\s*(\d{3})\b"
)


# =============================================================================
# Patent ID patterns
# =============================================================================

# US patent number: "7,629,993" or "US7629993B2"
US_PATENT_RE = re.compile(
    r"\b(?:US\s*)?([0-9]{1,2}),?([0-9]{3}),?([0-9]{3})\s*([A-Z][0-9])?\b",
    re.IGNORECASE,
)

# US publication number: "2009/0123456" or "2009/0123456 A1"
US_PUBLICATION_RE = re.compile(
    r"\b(20\d{2})/(\d{7})\s*([A-Z]\d)?\b"
)


# =============================================================================
# Section heading patterns (for body parsing)
# =============================================================================

# Background section
BACKGROUND_HEADING_RE = re.compile(
    r"\b(?:BACKGROUND(?:\s+OF)?(?:\s+THE)?(?:\s+INVENTION)?)\b",
    re.IGNORECASE,
)

# Summary section
SUMMARY_HEADING_RE = re.compile(
    r"\b(?:SUMMARY(?:\s+OF)?(?:\s+THE)?(?:\s+INVENTION)?)\b",
    re.IGNORECASE,
)

# Brief description of drawings
BRIEF_DESCRIPTION_HEADING_RE = re.compile(
    r"\b(?:BRIEF\s+DESCRIPTION\s+OF\s+THE\s+(?:DRAWINGS|FIGURES))\b",
    re.IGNORECASE,
)

# Detailed description
DETAILED_DESCRIPTION_HEADING_RE = re.compile(
    r"\b(?:DETAILED\s+DESCRIPTION(?:\s+OF)?(?:\s+THE)?(?:\s+INVENTION)?(?:\s+EMBODIMENT)?)\b",
    re.IGNORECASE,
)

# Claims section
CLAIMS_HEADING_RE = re.compile(
    r"\b(?:CLAIMS?|What\s+is\s+claimed|The\s+invention\s+claimed)\b",
    re.IGNORECASE,
)


# =============================================================================
# Utility functions for pattern matching
# =============================================================================

def parse_fig_id(fig_str: str) -> tuple[int, str | None]:
    """Parse figure ID string into number and optional suffix.

    Args:
        fig_str: Figure ID like "3", "3A", "2B"

    Returns:
        Tuple of (figure_number, suffix_letter or None)

    Raises:
        ValueError: If figure string doesn't match expected format

    Examples:
        >>> parse_fig_id("3")
        (3, None)
        >>> parse_fig_id("3A")
        (3, 'A')
    """
    m = FIG_ID_RE.match(fig_str.strip())
    if not m:
        raise ValueError(f"Invalid figure id: {fig_str!r}")
    n = int(m.group(1))
    s = m.group(2)
    return n, (s.upper() if s else None)
