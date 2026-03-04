from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Iterable

from pypdf import PdfReader


# -----------------------------------------------------------------------------
# Constants for heuristic thresholds
# -----------------------------------------------------------------------------

# Claim validation
MIN_CLAIM_LENGTH = 30  # Minimum character length for a valid claim (filters out page numbers)

# Claims search positioning
CLAIMS_SEARCH_START_RATIO = 0.30  # Start searching for claims anchor from 30% into document
CLAIMS_TAIL_START_RATIO = 0.60  # Fallback tail search starts at 60% of document

# Minimum document sizes
MIN_BODY_TEXT_LENGTH = 2000  # Minimum chars in body text to attempt claims extraction

# Claims region detection (tail fallback)
CLAIMS_WINDOW_SIZE = 25000  # Character window size for evaluating potential claims regions
MIN_CLAIMS_IN_WINDOW = 5  # Minimum claim markers required in a window
MAX_CLAIM_OVERRUN_RATIO = 1.2  # Allow 20% overrun vs expected claim count (for OCR errors)
MAX_CLAIM_OVERRUN_BUFFER = 3  # Additional fixed buffer for claim count overrun

# Scoring weights for tail region detection
SCORE_WEIGHT_COUNT = 2  # Points per claim marker found
SCORE_WEIGHT_INCREASE = 2  # Points per increasing transition (e.g., 2→5)
SCORE_WEIGHT_SEQUENTIAL = 3  # Points per perfectly sequential transition (e.g., 5→6)
SCORE_PENALTY_BACK_JUMP = 10  # Penalty for large backward jumps (e.g., 20→2)
BACK_JUMP_THRESHOLD = 3  # Minimum backward jump size to penalize


# -----------------------------------------------------------------------------
# Normalization utilities
# -----------------------------------------------------------------------------


def _normalize_text(text: str) -> str:
    """
    Keep normalization conservative:
    - normalize newline variants
    - do not aggressively collapse whitespace (we rely on offsets for spans)
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def _normalize_space_for_matching(text: str) -> str:
    """
    Create a match-friendly view of text.
    NOTE: Not used for slicing (offsets would not match). Only for auxiliary matching.
    """
    return re.sub(r"\s+", " ", text).strip()


# -----------------------------------------------------------------------------
# Section heading patterns (tolerant, USPTO-friendly)
# -----------------------------------------------------------------------------

SECTION_HEADINGS: Dict[str, List[str]] = {
    "background": [
        "background",
        "background of the invention",
        "background art",
    ],
    "summary": [
        "summary",
        "summary of the invention",
    ],
    "brief_description_of_drawings": [
        "brief description of the drawings",
        "brief description of drawings",
        "description of the drawings",
        "description of drawings",
    ],
    "detailed_description": [
        "detailed description",
        "detailed description of the invention",
        "description of embodiments",
    ],
    # Claims may not have a "CLAIMS" heading; include common intro markers.
    "claims": [
        "claims",
        "the invention claimed is",
        "what is claimed is",
        "i/we claim",
    ],
}


def _phrase_to_ws_regex(phrase: str) -> str:
    """
    Convert a heading phrase into a regex that tolerates arbitrary whitespace and punctuation.
    Example: "BRIEF DESCRIPTION OF THE DRAWINGS" ->
             r"brief\s+description\s+of\s+the\s+drawings"
    """
    # Keep alphanumerics and spaces, then split into tokens.
    cleaned = re.sub(r"[^A-Za-z0-9\s/]", " ", phrase)
    tokens = [t for t in re.split(r"\s+", cleaned.strip()) if t]
    # join tokens with whitespace tolerance
    return r"\b" + r"\s+".join(map(re.escape, tokens)) + r"\b"


@dataclass(frozen=True)
class _HeadingHit:
    start: int
    end: int
    section: str
    matched: str


def _uppercase_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)


def _is_heading_context(text: str, start: int, end: int) -> bool:
    """
    Decide if a matched phrase is likely a true heading.

    Accept if:
    - near line boundaries (common in pypdf output when headings are on their own line), OR
    - the matched phrase is mostly uppercase (common for headings)
    """
    # Window around match
    pre = text[max(0, start - 3) : start]
    post = text[end : end + 3]

    near_boundary = ("\n" in pre) or ("\n" in post) or start == 0
    if near_boundary:
        return True

    matched = text[start:end]
    if _uppercase_ratio(matched) >= 0.6:
        return True

    return False


def _dedup_close_hits(hits: List[_HeadingHit], max_gap: int = 200) -> List[_HeadingHit]:
    out: List[_HeadingHit] = []
    for h in sorted(hits, key=lambda x: x.start):
        if (
            out
            and out[-1].section == h.section
            and (h.start - out[-1].start) <= max_gap
        ):
            # keep the later one if it looks more “heading-like” (longer match)
            if (h.end - h.start) > (out[-1].end - out[-1].start):
                out[-1] = h
            continue
        out.append(h)
    return out


def _find_heading_positions(text: str) -> List[_HeadingHit]:
    """
    Find headings anywhere in the text (position-based, not line-based).
    Returns hits sorted by start position.

    De-dupe strategy:
    - If multiple hits share the same start offset, keep the longest (most specific).
    - Then keep only the first occurrence per section key (practical for USPTO bodies).
    """
    hits: List[_HeadingHit] = []
    for section, phrases in SECTION_HEADINGS.items():
        for phrase in phrases:
            rx = re.compile(_phrase_to_ws_regex(phrase), flags=re.IGNORECASE)
            for m in rx.finditer(text):
                if not _is_heading_context(text, m.start(), m.end()):
                    continue
                hits.append(_HeadingHit(m.start(), m.end(), section, m.group(0)))

    if not hits:
        return []

    # Prefer longest match at same start
    hits.sort(key=lambda h: (h.start, -(h.end - h.start)))
    dedup_same_start: List[_HeadingHit] = []
    seen_start = None
    for h in hits:
        if seen_start == h.start:
            continue
        dedup_same_start.append(h)
        seen_start = h.start

    return sorted(_dedup_close_hits(dedup_same_start), key=lambda h: h.start)


def _split_sections_by_heading_positions(
    text: str,
) -> Tuple[Dict[str, str], Dict[str, Tuple[int, int]], List[dict]]:
    """
    Split by heading positions and return:
      - sections: section_key -> extracted text chunk
      - spans: section_key -> (start_char, end_char) in original `text`
      - headings_found: list of dicts (for QA)
    """
    hits = _find_heading_positions(text)
    sections: Dict[str, str] = {}
    spans: Dict[str, Tuple[int, int]] = {}
    headings_found: List[dict] = []

    if not hits:
        return sections, spans, headings_found

    for h in hits:
        headings_found.append(
            {"section": h.section, "start": h.start, "end": h.end, "matched": h.matched}
        )

    for i, h in enumerate(hits):
        content_start = h.end
        content_end = hits[i + 1].start if i + 1 < len(hits) else len(text)
        chunk = text[content_start:content_end].strip()
        sections[h.section] = chunk
        spans[h.section] = (content_start, content_end)

    return sections, spans, headings_found


# -----------------------------------------------------------------------------
# Claims extraction (anchor-first, tail numbered-list fallback)
# -----------------------------------------------------------------------------

# Standard claims anchor phrase regex
# Matches common introductory phrases that precede claim listings:
# - "what is claimed is:" (most common in US patents)
# - "the invention claimed is:"
# - "I/We claim:" or "I claim:" or "We claim:"
# The optional trailing colon handles both "what is claimed is:" and "what is claimed is"
_CLAIMS_ANCHOR_RX = re.compile(
    r"\b(the\s+invention\s+claimed\s+is|what\s+is\s+claimed\s+is|i\s*/\s*we\s+claim)\b\s*:?",
    re.IGNORECASE,
)

# Claim start marker regex - matches numbered claim beginnings in PDF-extracted text
#
# This regex is designed to robustly identify claim starts while avoiding false positives
# from page numbers, figure references, and paragraph numbers. It uses two branches:
#
# Branch 1 (normal claim markers):
#   - Matches: "1. A method...", "2. The system...", "10) An apparatus..."
#   - Requires: claim number (1-999) followed by punctuation separator (. ) : or -)
#   - Lookbehind: avoids matching "claim 1" or "claims 1" (not a claim start)
#   - Lookahead: requires a letter after separator (claims start with words)
#   - Handles OCR corruption: "15-4 A..." where "." becomes "-4"
#
# Branch 2 (OCR-dropped punctuation at line start):
#   - Only matches at true line start (^) to avoid inline numbers
#   - Matches: "1 A method..." (period was dropped by OCR)
#   - Requires: claim number followed by space and capitalized claim-like word
#   - Capitalization requirement: avoids "10\nan analyzer" where 10 is a line number
#   - Only accepts: "A", "An", "The", "Means" (common claim starters)
#
# Capture group (1) or (2): the claim number as a string (e.g., "1", "15", "100")
#
# Limitations:
#   - If OCR completely drops a claim number, it cannot be matched
#   - Downstream code should tolerate gaps in claim numbering
_CLAIM_START_MARKER_RX = re.compile(
    r"""(?mix)
    (?:  # Branch 1: normal claim markers (inline or line-start), requires a real separator
        (?:^|(?<=\s))                           # start of line or after whitespace
        [\'"''""\(\[\{]*\s*                     # optional opening quotes/brackets
        (?<!claim\s)(?<!claims\s)               # NOT preceded by "claim " or "claims "
        (\d{1,3})                               # capture group 1: claim number (1-999)
        \s*
        (?:[.)]|:|[-–—]\s*\d{0,2})              # separator: period, paren, colon, or dash (handles OCR "-4" for ".")
        \s*
        (?=[\'"''""\(\[\{]?\s*[A-Za-z])         # lookahead: optional quote then letter
    )
    |
    (?:  # Branch 2: OCR-dropped punctuation at *true line start* only
        ^                                       # must be at line start
        \s*[\'"''""\(\[\{]*\s*                  # optional leading whitespace/quotes
        (?<!claim\s)(?<!claims\s)               # NOT preceded by "claim " or "claims "
        (\d{1,3})                               # capture group 2: claim number (1-999)
        \s+                                     # required whitespace (no punctuation)
        (?=(?-i:(?:A|An|The|Means)\b))          # lookahead: capitalized claim starter word (case-sensitive)
    )
    """,
    re.MULTILINE | re.IGNORECASE | re.VERBOSE,
)


# Pattern to validate if text looks like a claim
# Independent claims typically start with articles ("A method", "An apparatus")
# Dependent claims reference other claims ("The method of claim 1", "Claim 1 further comprising")
# This pattern matches these common claim structures
_CLAIM_START_PATTERN = re.compile(
    r"^\d{1,3}\.\s+(?:"
    r"(?:A|An|The)\s+\w+|"                      # Independent: "1. A method", "2. An apparatus", "3. The system"
    r"(?:In|For|As|According\s+to)\s+|"         # Variations: "In embodiments", "According to claim"
    r"\w+\s+of\s+claim\s+\d+|"                  # Dependent: "The method of claim 1"
    r"Claim\s+\d+\s+further\s+comprising"       # Dependent: "Claim 1 further comprising"
    r")",
    re.IGNORECASE,
)


def _looks_like_claim(chunk: str) -> bool:
    """
    Heuristic to determine if a text chunk looks like an actual patent claim.

    This function filters out false positives from _CLAIM_START_MARKER_RX by checking
    whether the extracted chunk has claim-like characteristics.

    Validation strategy:
    1. Reject chunks that are too short (< 30 chars) - claims are typically substantial
    2. Check for explicit claim patterns (articles + nouns, claim references)
    3. Check for positive indicators (claim vocabulary: "comprising", "wherein", etc.)
    4. Reject chunks with negative indicators (figure refs, page numbers, section headers)

    Returns:
        True if the chunk appears to be a genuine patent claim.
        False if it's likely a false positive (page number, figure reference, etc.)
    """
    # Minimum length check: claims are typically substantial
    # This filters out page numbers like "10. " and figure refs like "15. "
    if not chunk or len(chunk) < MIN_CLAIM_LENGTH:
        return False

    # Primary validation: does it match explicit claim start patterns?
    # Matches: "1. A method...", "2. The apparatus of claim 1...", etc.
    if _CLAIM_START_PATTERN.match(chunk):
        return True

    # Secondary validation: check for claim-like vocabulary in the first 100 chars
    # This catches claims that don't match the explicit pattern but are clearly claims
    prefix = chunk[:100].lower()

    # Positive indicators: patent claim vocabulary
    # These words/phrases are common in claims but rare in other parts of patents
    claim_indicators = [
        r"\ba\s+(?:method|apparatus|system|device|process|composition)",  # Independent claim intros
        r"\ban\s+(?:apparatus|assembly|element)",                         # Independent claim intros
        r"\bthe\s+(?:method|apparatus|system|device)\s+of\s+claim",       # Dependent claim refs
        r"\bcomprising\b",                                                # Transition word (open-ended)
        r"\bwherein\b",                                                   # Claim limitation introducer
    ]

    has_indicator = any(re.search(pat, prefix) for pat in claim_indicators)

    # Negative indicators: things that suggest it's NOT a claim
    # These patterns appear in figure references, page numbers, section headers, etc.
    non_claim_markers = [
        r"\bfig\.",  # Figure references: "FIG. 1", "fig. 2"
        r"\btable\s+\d+",  # Table references
        r"\bpage\s+\d+",  # Page references
        r"\bparagraph\s+\d+",  # Paragraph references
        r"^\d+\.\s+(?:background|summary|description|embodiment)",  # Section headers
    ]

    has_non_marker = any(re.search(pat, prefix) for pat in non_claim_markers)

    return has_indicator and not has_non_marker


def _find_claims_start_offset(body_text: str) -> Optional[int]:
    # 1) Anchor phrase is the most reliable
    m = _CLAIMS_ANCHOR_RX.search(body_text)
    if m:
        return m.start()

    # 2) Tail numbered-list fallback
    tail_region = _find_claims_region_tail(body_text)
    if tail_region:
        start, _end, _diag = tail_region
        return start

    return None


_END_MARKERS_RX = re.compile(
    r"\b(?:"
    r"ABSTRACT\s+OF\s+THE\s+(?:DISCLOSURE|INVENTION)|"
    r"END\s+OF\s+CLAIMS|"
    r"WHAT\s+IS\s+CLAIMED\s+ABOVE"
    r")\b",
    re.IGNORECASE,
)

_ALL_CAPS_HEADER_RX = re.compile(
    r"^(?!.*[a-z])[A-Z\s]{20,}$",  # no lowercase allowed
    re.MULTILINE,
)

_ASTERISK_SEP_RX = re.compile(
    r"^\s*(?:\*\s*){3,}$",  # "***" or "* * *" etc.
    re.MULTILINE,
)


def _find_claims_end_offset(block: str, start_offset: int = 0) -> Optional[int]:
    """
    Best-effort claims end detection.

    Robustness notes:
    - OCR/PDF extraction often skips claim numbers or corrupts separators (e.g., "15-4" for "15.").
      Therefore we do NOT treat skipped numbers as an end-of-claims signal.
    - We only stop early on explicit end markers / structural separators, or a clear numbering restart.
    """
    if not block:
        return None

    # check the explicit markers (case-insensitive)
    m = _END_MARKERS_RX.search(block, start_offset)
    if m:
        # print("Found end of claims marker:", m.group(0), "at offset", m.start())
        return m.start()

    # check separators / all-caps headers (case-sensitive / structural)
    m = _ASTERISK_SEP_RX.search(block, start_offset)
    if m:
        # print("Found end of claims marker:", m.group(0), "at offset", m.start())
        return m.start()

    m = _ALL_CAPS_HEADER_RX.search(block, start_offset)
    if m:
        # print("Found end of claims marker:", m.group(0), "at offset", m.start())
        return m.start()

    # Numbering-based heuristic (tolerant to skips)
    matches = list(_CLAIM_START_MARKER_RX.finditer(block, start_offset))
    if len(matches) < 2:
        return None
    claim_numbers = [int(m.group(1)) for m in matches]
    # print("Claim numbers detected for end detection:", claim_numbers[:20])

    for i in range(1, len(claim_numbers)):
        prev_num = claim_numbers[i - 1]
        curr_num = claim_numbers[i]

        # Restart or large backward jump (e.g., 20 -> 1, or 15 -> 2)
        if curr_num < prev_num and (prev_num - curr_num) > 3:
            return matches[i].start()

    return None


def _parse_claims_from_block(
    block: str, expected_count: Optional[int] = None
) -> List[str]:
    if not block:
        return []

    # print("Parsing claims block of length", len(block))
    # print("Block preview:", block)

    # Detect end of claims section
    claims_end = _find_claims_end_offset(block)
    if claims_end is not None:
        block = block[:claims_end]

    # print("Trimmed claims block length after end detection:", len(block))

    starts = list(_CLAIM_START_MARKER_RX.finditer(block))
    if not starts:
        return []

    claims: List[str] = []
    claim_numbers: List[int] = []

    for i, m in enumerate(starts):
        claim_num_str = m.group(1)
        claim_num = int(claim_num_str)

        # Slice from the NUMBER start (group(1)) to the next NUMBER start
        start_pos = m.start(1)
        end_pos = starts[i + 1].start(1) if i + 1 < len(starts) else len(block)
        chunk = block[start_pos:end_pos].strip()

        # print(f"Found claim {claim_num} at offset {start_pos}, chunk preview: {chunk}")

        # Deterministic whitespace normalization inside each claim
        chunk = re.sub(r"\s+", " ", chunk).strip()

        # Canonicalize the claim prefix to "<n>." (handles OCR like "15-4 ..." or "15) ...")
        chunk = re.sub(
            rf"^{re.escape(claim_num_str)}\s*(?:[\)\.:]|[-–—]\s*\d{{0,2}})\s*",
            f"{claim_num_str}. ",
            chunk,
        )

        # Validate that this looks like an actual claim
        if not _looks_like_claim(chunk):
            # If we've already found claims and hit something that doesn't look like a claim,
            # it's likely we've left the claims section
            if claims:
                break
            # Otherwise skip this match and continue
            continue

        # Detect breaks in sequential numbering during iteration:
        # - tolerate skipped numbers (OCR drops claim numbers)
        # - stop only on restart / large backward jump
        if claim_numbers:
            prev_num = claim_numbers[-1]
            if claim_num < prev_num and (prev_num - claim_num) > 3:
                break

        # If expected_count provided and we've exceeded it significantly, stop
        # Allow some overrun for OCR errors in front matter
        if expected_count and len(claims) >= int(expected_count * MAX_CLAIM_OVERRUN_RATIO) + MAX_CLAIM_OVERRUN_BUFFER:
            break

        claims.append(chunk)
        claim_numbers.append(claim_num)

    return claims


def _find_claims_region_tail(text: str) -> Optional[Tuple[int, int, dict]]:
    """
    Find a plausible claims region in the tail of the document using numbering heuristics.

    This is a fallback method used when the anchor phrase ("what is claimed is:") cannot
    be found. It searches the latter 40% of the document for clusters of numbered items
    that look like claims based on their numbering pattern.

    Strategy:
    1. Search only in the tail (last 40% of document) to avoid false positives from
       numbered section headings in the front matter (e.g., "B2 1. SYSTEM OVERVIEW")
    2. Evaluate candidate windows starting at each potential claim marker
    3. Score each window based on:
       - Density: number of claim markers found (more = better)
       - Sequentiality: how many consecutive numbers (1→2, 5→6, etc.)
       - Monotonicity: numbers should generally increase
       - Back jumps: large backward jumps (20→2) indicate false positives
    4. Return the window with the highest score

    Robustness notes:
    - OCR often skips numbers (e.g., missing claim 7) or corrupts separators (e.g., "15-4")
    - We do NOT require perfectly sequential numbering
    - We just want a dense cluster of mostly-increasing numbers

    Returns:
        Tuple of (start_offset, end_offset, diagnostics_dict) if found, else None.
        Offsets are character positions in the original text.
    """
    if not text:
        return None

    # Restrict to tail to avoid false positives in headers like "... B2 1. SYSTEM ..."
    # Claims sections are typically at the end of the patent document
    tail_start = int(len(text) * CLAIMS_TAIL_START_RATIO)
    tail = text[tail_start:]

    matches = list(_CLAIM_START_MARKER_RX.finditer(tail))
    if len(matches) < 2:  # Need at least 2 potential claims to form a region
        return None

    # Evaluate each potential starting point
    best = None
    best_score = -1
    best_diag: dict = {}

    idx_by_pos = [(m.start(), int(m.group(1))) for m in matches]

    # Try each match position as a potential claims region start
    for pos_i, _ in idx_by_pos:
        # Fixed window size (typical claim: 200-500 chars, typical patent: 20-50 claims)
        window_end = min(len(tail), pos_i + CLAIMS_WINDOW_SIZE)
        window = tail[pos_i:window_end]

        # Find all claim-like numbers in this window
        ws = [int(m.group(1)) for m in _CLAIM_START_MARKER_RX.finditer(window)]
        if len(ws) < MIN_CLAIMS_IN_WINDOW:  # Too few claims; skip this window
            continue

        # Score this window based on numbering quality
        inc = 0          # Count of increasing transitions (2→5, 10→11, etc.)
        seq = 0          # Count of perfectly sequential transitions (1→2, 5→6, etc.)
        back_jumps = 0   # Count of large backward jumps (20→2, likely false positive)

        for a, b in zip(ws, ws[1:]):
            if b > a:
                inc += 1               # Number increased (good)
                if b == a + 1:
                    seq += 1           # Perfectly sequential (even better)
            elif b < a and (a - b) > BACK_JUMP_THRESHOLD:
                back_jumps += 1        # Large backward jump (bad - likely not claims)

        # Scoring heuristic (empirically tuned):
        # Rewards density, monotonicity, and sequentiality; penalizes false positive patterns
        score = (
            (len(ws) * SCORE_WEIGHT_COUNT)
            + (inc * SCORE_WEIGHT_INCREASE)
            + (seq * SCORE_WEIGHT_SEQUENTIAL)
            - (back_jumps * SCORE_PENALTY_BACK_JUMP)
        )

        if score > best_score:
            best_score = score
            best = (tail_start + pos_i, tail_start + window_end)
            best_diag = {
                "tail_start": tail_start,
                "window_start": tail_start + pos_i,
                "window_end": tail_start + window_end,
                "claim_starts_in_window": len(ws),
                "increases": inc,
                "sequential_transitions": seq,
                "back_jumps": back_jumps,
                "score": score,
                "first_numbers": ws[:10],
            }

    if best is None:
        return None

    return best[0], best[1], best_diag


def _extract_claims_block(
    body_text: str,
    sections: Dict[str, str],
    qa: dict,
) -> str:
    """
    Extract the best-effort claims block using the recommended cascade:
    1) anchor phrase search
    2) tail numbered-list detection
    3) (optional) section["claims"] if it exists and looks valid
    """
    # 1) Anchor phrase (preferred)
    m = _CLAIMS_ANCHOR_RX.search(body_text)
    if m:
        qa["info"]["claims_extraction_method"] = "anchor"
        qa["info"]["claims_anchor"] = m.group(1)
        return body_text[m.end() :].strip()

    # 2) Tail numbered list (fallback)
    tail_region = _find_claims_region_tail(body_text)
    if tail_region:
        start, end, diag = tail_region
        qa["info"]["claims_extraction_method"] = "tail_numbered_list"
        qa["info"]["claims_region"] = {"start": start, "end": end, **diag}
        qa["warnings"].append("claims_section_fallback_used")
        return body_text[start:].strip()  # claims usually run to end

    # 3) Section-based claims (only if present; last resort)
    claims_section = (sections.get("claims") or "").strip()
    if claims_section:
        qa["info"]["claims_extraction_method"] = "section_claims"
        return claims_section

    qa["info"]["claims_extraction_method"] = "none"
    return ""


# -----------------------------------------------------------------------------
# Figure reference parsing
# -----------------------------------------------------------------------------


# Capture a FIG/FIGS reference followed by a "figlist" chunk that may include:
# - single ids: 1, 2A
# - ranges: 1A-1C, 3-5
# - lists: 2, 3 and 4
# - mixed: 1A-1C, 2 and 3
_FIG_REF_RE = re.compile(
    r"\bFIGS?\.?\s+"
    r"(?P<figlist>"
    r"(?:\d+[A-Z]?)"
    r"(?:\s*[-–]\s*\d+[A-Z]?)?"
    r"(?:\s*(?:,|and)\s*\d+[A-Z]?)*"
    r")",
    re.IGNORECASE,
)

_FIG_ID_RX = re.compile(r"^\s*(\d+)\s*([A-Z])?\s*$", re.IGNORECASE)


def _parse_fig_id(fig: str) -> tuple[int, Optional[str]]:
    """
    '3'  -> (3, None)
    '3A' -> (3, 'A')
    """
    m = _FIG_ID_RX.match(fig.strip())
    if not m:
        raise ValueError(f"Invalid figure id: {fig!r}")
    n = int(m.group(1))
    s = m.group(2)
    return n, (s.upper() if s else None)


def _expand_fig_range(start: str, end: str) -> List[str]:
    """
    Expand:
      2-5   -> ['2','3','4','5']
      2A-2C -> ['2A','2B','2C']
    Otherwise returns [start,end] as best effort.
    """
    if start == end:
        return [start]

    m1 = re.match(r"(\d+)([A-Z]?)", start, flags=re.IGNORECASE)
    m2 = re.match(r"(\d+)([A-Z]?)", end, flags=re.IGNORECASE)
    if not m1 or not m2:
        return [start, end]

    n1, s1 = m1.groups()
    n2, s2 = m2.groups()
    n1i = int(n1)
    n2i = int(n2)

    # numeric range like 2-5
    if not s1 and not s2 and n1i <= n2i:
        return [str(i) for i in range(n1i, n2i + 1)]

    # letter suffix range like 2A-2C
    if n1 == n2 and s1 and s2:
        a = ord(s1.upper())
        b = ord(s2.upper())
        if a <= b:
            return [f"{n1}{chr(c)}" for c in range(a, b + 1)]

    return [start, end]


# Matches:
#   FIG. 1 ...
#   FIGS. 1A-1C ...
#   FIGS. 2, 3 and 4 ...
# Captures the figure list chunk and leaves the description to be sliced separately.
_DRAWINGS_ENTRY_RX = re.compile(
    r"\bFIGS?\.?\s+"
    r"(?P<figlist>"
    r"(?:\d+[A-Z]?)"
    r"(?:\s*[-–]\s*\d+[A-Z]?)?"
    r"(?:\s*(?:,|and)\s*\d+[A-Z]?)*"
    r")",
    re.IGNORECASE,
)


def _parse_figlist(figlist: str) -> List[str]:
    """
    Parse the 'figlist' part into normalized figure id strings (e.g., ['1', '2A', '2B']).
    Supports:
      - single: '3', '3A'
      - range: '1A-1C', '2-5'
      - comma/and: '2, 3 and 4'
      - combined: '1A-1C, 2 and 3'
    """
    s = figlist.strip()
    # Normalize separators
    s = re.sub(r"\s+", " ", s)
    s = s.replace("–", "-")
    parts = re.split(r"\s*(?:,|and)\s*", s, flags=re.IGNORECASE)

    out: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if "-" in p:
            a, b = [x.strip() for x in p.split("-", 1)]
            out.extend(_expand_fig_range(a, b))
        else:
            out.append(p)

    # Dedup while preserving order
    seen = set()
    dedup: List[str] = []
    for x in out:
        x = x.upper()
        if x in seen:
            continue
        seen.add(x)
        dedup.append(x)
    return dedup


def _extract_figure_ids(text: str) -> List[str]:
    """
    Best-effort extraction of figure identifiers referenced in the body text.
    Supports FIG. 1, FIGS. 2 and 3, FIGS. 2, 3 and 4, FIGS. 1A-1C, FIGS. 3-5, etc.

    Returns sorted unique ids in canonical string form (e.g., '2A', '3').
    """
    if not text:
        return []

    ids: List[str] = []
    for m in _FIG_REF_RE.finditer(text):
        figlist = m.group("figlist")
        try:
            # Reuse the same figlist parsing used for drawing descriptions.
            # _parse_figlist should expand ranges and handle ", and" lists.
            ids.extend(_parse_figlist(figlist))
        except Exception:
            # Best-effort: ignore malformed references
            continue

    return sorted(set(ids))


def extract_drawing_descriptions(text: str) -> List[dict]:
    """
    Convert 'Brief Description of the Drawings' prose into a table:
      [{'figure_number': int, 'figure_suffix': Optional[str], 'description': str, 'raw_reference': str}, ...]
    Strategy:
      - find each FIG/FIGS occurrence
      - description is from end of that match to start of next FIG/FIGS (or end)
      - expand fig lists/ranges so each figure id gets a row with the same description
    """
    if not text:
        return []

    # Make spacing stable for slicing but do not remove all punctuation.
    # (We keep original `text` to slice descriptions deterministically.)
    matches = list(_DRAWINGS_ENTRY_RX.finditer(text))
    if not matches:
        return []

    rows: List[dict] = []
    for i, m in enumerate(matches):
        figlist = m.group("figlist")
        fig_ids = _parse_figlist(figlist)

        desc_start = m.end()
        desc_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        desc = text[desc_start:desc_end].strip()
        desc = re.sub(r"\s+", " ", desc).strip()

        raw_ref_prefix = (
            "FIGS."
            if re.match(r"\bFIGS\b", m.group(0), flags=re.IGNORECASE)
            else "FIG."
        )
        for fig_id in fig_ids:
            try:
                n, suf = _parse_fig_id(fig_id)
            except ValueError:
                continue
            rows.append(
                {
                    "figure_number": n,
                    "figure_suffix": suf,
                    "description": desc,
                    "raw_reference": f"{raw_ref_prefix} {fig_id}",
                }
            )

    return rows


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def parse_patent_body(
    *,
    pdf_path: str,
    start_page_index: int | None,
    output_dir: str | None = None,
    expected_claim_count: int | None = None,
    expected_drawing_count: int | None = None,
    expected_sheet_count: int | None = None,
) -> dict:
    qa = {"warnings": [], "info": {}}

    reader = PdfReader(pdf_path)
    num_pages = len(reader.pages)

    # Validate start page
    if start_page_index is None:
        qa["warnings"].append("start_page_index_missing")
        start_used = 1 if num_pages > 1 else 0
    elif not isinstance(start_page_index, int) or start_page_index < 0:
        qa["warnings"].append("start_page_index_invalid")
        start_used = 1 if num_pages > 1 else 0
    elif start_page_index >= num_pages:
        qa["warnings"].append("start_page_index_out_of_range")
        start_used = 1 if num_pages > 1 else 0
    else:
        start_used = start_page_index

    if start_used == 0 and num_pages > 1:
        qa["warnings"].append("start_page_index_is_cover_page")

    qa["info"]["start_page_index_used"] = start_used
    qa["info"]["pdf_num_pages"] = num_pages

    texts: List[str] = []
    for i in range(start_used, num_pages):
        from doc_extractor.two_column import extract_page_text_two_column

        page_text = extract_page_text_two_column(reader, i)
        # page_text = reader.pages[i].extract_text() or ""
        texts.append(page_text)

    body_text = _normalize_text("\n".join(texts))
    qa["info"]["body_pages_count"] = num_pages - start_used

    # Section splitting (position-based)
    sections, spans, headings_found = _split_sections_by_heading_positions(body_text)

    drawings_text = sections.get("brief_description_of_drawings", "")
    drawings_items = extract_drawing_descriptions(drawings_text)

    # Optional fallback: if the section is missing/empty, try from entire body text
    if not drawings_items:
        drawings_items = extract_drawing_descriptions(body_text)
        if drawings_items:
            qa["warnings"].append("drawings_descriptions_fallback_used")

    qa["info"]["drawings_descriptions_count"] = len(drawings_items)

    claims_start = _find_claims_start_offset(body_text)
    if claims_start is not None:
        qa["info"]["claims_start_offset"] = claims_start

        # Trim narrative sections so they never include claims.
        for key in (
            "background",
            "summary",
            "brief_description_of_drawings",
            "detailed_description",
        ):
            if key in spans:
                s, e = spans[key]
                if e > claims_start:
                    spans[key] = (s, min(e, claims_start))
                    sections[key] = body_text[spans[key][0] : spans[key][1]].strip()

    # Ensure a claims section exists and is exactly the claims block
    if "claims" not in sections:
        sections["claims"] = body_text[claims_start:].strip()
        spans["claims"] = (claims_start, len(body_text))
    if not sections:
        qa["warnings"].append("no_section_headings_detected")
    if spans:
        qa["info"]["section_spans"] = spans
    if headings_found:
        qa["info"]["headings_found"] = headings_found

    # Claims: robust extraction cascade
    claims_block = _extract_claims_block(body_text, sections, qa)
    claims_items = _parse_claims_from_block(claims_block)
    claims_count = len(claims_items)

    if expected_claim_count is not None and expected_claim_count != claims_count:
        qa["warnings"].append("claims_count_mismatch")
        qa["info"]["claims"] = {
            "expected": expected_claim_count,
            "actual": claims_count,
        }

    # Figures
    figure_ids = _extract_figure_ids(body_text)
    fig_count = len(figure_ids)

    if expected_drawing_count is not None:
        # tolerant comparison
        if abs(fig_count - expected_drawing_count) > max(
            1, expected_drawing_count // 2
        ):
            qa["warnings"].append("drawing_count_inconsistent")
            qa["info"]["figures"] = {
                "expected": expected_drawing_count,
                "actual": fig_count,
            }

    # Artifacts
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

        with open(
            os.path.join(output_dir, "body_text.txt"), "w", encoding="utf-8"
        ) as f:
            f.write(body_text)

        with open(os.path.join(output_dir, "claims.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"count": claims_count, "items": claims_items},
                f,
                indent=2,
                ensure_ascii=False,
            )

    result = {
        "sections": sections,
        "claims": {
            "count": claims_count,
            "items": claims_items,
        },
        "figures": {
            "figure_reference_count": fig_count,
            "figure_ids": figure_ids,
            "items": drawings_items,
        },
        "qa": qa,
    }
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "debug.json"), "w", encoding="utf-8") as f:
            json.dump(
                result,
                f,
                indent=2,
                ensure_ascii=False,
            )

    return result
