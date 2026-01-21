from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Tuple, Optional, Iterable, Any

from patent_ingest.claims import Claim
from patent_ingest.diagnostics import Diagnostics
from patent_ingest.model.document import MultiPage
from patent_ingest.common import patterns


# -----------------------------------------------------------------------------
# Fallible result types (new diagnostics framework)
# -----------------------------------------------------------------------------


class PatentBodyStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class PatentBodyPolicy:
    """Controls how strict body parsing should be."""

    # If True, missing claims is an ERROR (else WARN).
    require_claims: bool = True

    # If True, missing drawings section/descriptions is an ERROR (else WARN).
    require_drawings: bool = False

    # If True, any diagnostics errors => FAILED. Otherwise errors still yield PARTIAL.
    fail_on_error: bool = False


@dataclass(frozen=True)
class ClaimsData:
    count: int
    items: Tuple[Claim, ...]
    method: str


@dataclass(frozen=True)
class FiguresData:
    figure_reference_count: int
    figure_ids: Tuple[str, ...]
    items: Tuple[dict, ...]


@dataclass(frozen=True)
class PatentBodyData:
    """Structured output of body parsing."""

    sections: Dict[str, str]
    section_spans: Dict[str, Tuple[int, int]]
    claims: ClaimsData
    figures: FiguresData
    headings_found: Tuple[dict, ...] = tuple()
    meta: Dict[str, Any] = field(default_factory=dict)

    def canonical_sections(self) -> dict[str, str]:
        return {
            k: v
            for k, v in self.sections.items()
            if k in {"background", "summary", "detailed_description"}
        }

    def canonical_claims(self) -> list[dict]:
        """Return claims in v1.1 format compatible with bundle_v1_1.ClaimV1_1."""
        return [
            {
                "number": c.number,
                "text": c.text,
                "depends_on": c.depends_on,
                "is_independent": c.is_independent,
            }
            for c in self.claims.items
        ]

    def canonical_figures(self) -> list[dict]:
        """Return figure descriptions in v1.1 format compatible with bundle_v1_1.FigureDescriptionV1_1."""
        return list(self.figures.items)


@dataclass(frozen=True)
class PatentBodyResult:
    status: PatentBodyStatus
    data: Optional[PatentBodyData]
    diagnostics: Diagnostics
    meta: Dict[str, Any] = field(default_factory=dict)


def _diag_info(diag: Diagnostics, code: str, message: str, **kwargs: Any) -> None:
    """Compatibility shim: some harnesses use info_msg, some use info."""
    if hasattr(diag, "info_msg"):
        diag.info_msg(code, message, **kwargs)
    elif hasattr(diag, "info"):
        diag.info(code, message, **kwargs)
    else:
        # If no info channel exists, ignore.
        return


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

_CLAIMS_ANCHOR_RX = re.compile(
    r"\b(the\s+invention\s+claimed\s+is|what\s+is\s+claimed\s+is|i\s*/\s*we\s+claim)\b\s*:?",
    re.IGNORECASE,
)

# Matches claim starts at:
# - start of string, OR
# - after whitespace/newline, but not after letters/digits (avoids "FIG. 1", "claim 1", etc. as much as possible)
# Requires: "<num>." followed by a space and a capital letter (claims usually start with "A", "The", etc.)
_CLAIM_START_MARKER_RX = re.compile(
    r"(?:^|(?<=\s))"  # start or whitespace boundary
    r"(?<![A-Za-z0-9])"  # not immediately preceded by alnum
    r"(\d{1,3})\s*\.\s+"  # N. (claim number)
    r"(?=[A-Z])",  # next char likely starts a sentence/claim
    re.MULTILINE,
)


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


# Works with merged two-column text, e.g., "... 13.The ... 16.The ..."
# while excluding "claim 12." references.
CLAIM_ANY_RE = re.compile(r"(?i)(?<!claim\s)(?<!claims\s)\b(\d{1,3})\.(?=\s*[A-Z])")

DEPENDENCY_RE = re.compile(r"\bclaim(?:s)?\s+(\d+)(?:\s*[-–]\s*(\d+))?", re.IGNORECASE)


def _parse_claims_from_block(claims_text: str) -> list[Claim]:
    matches = list(CLAIM_ANY_RE.finditer(claims_text))
    if not matches:
        return []

    claims: list[Claim] = []
    for i, m in enumerate(matches):
        no = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(claims_text)
        body = claims_text[m.end() : end].strip()
        body = _clean(body)

        deps = _extract_dependencies(body)
        is_ind = len(deps) == 0
        claims.append(
            Claim(number=no, text=body, depends_on=deps, is_independent=is_ind)
        )

    # Deduplicate if merged text causes accidental repeats
    out = []
    seen = set()
    for c in claims:
        if c.number in seen:
            continue
        seen.add(c.number)
        out.append(c)
    return out


def _clean(t: str) -> str:
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _extract_dependencies(claim_body: str) -> list[int]:
    deps: set[int] = set()
    for m in DEPENDENCY_RE.finditer(claim_body):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else None
        if b is None:
            deps.add(a)
        else:
            lo, hi = min(a, b), max(a, b)
            for x in range(lo, hi + 1):
                deps.add(x)
    return sorted(deps)


# def _parse_claims_from_block(block: str) -> List[str]:
#     if not block:
#         return []
#
#     starts = list(_CLAIM_START_MARKER_RX.finditer(block))
#     if not starts:
#         return []
#
#     claims: List[str] = []
#     for i, m in enumerate(starts):
#         claim_num = m.group(1)
#         start_pos = m.start(1)  # start at the number
#         end_pos = starts[i + 1].start(1) if i + 1 < len(starts) else len(block)
#         chunk = block[start_pos:end_pos].strip()
#
#         # Deterministic whitespace normalization inside each claim
#         chunk = re.sub(r"\s+", " ", chunk).strip()
#
#         # Ensure "<n>." prefix is present
#         if not re.match(rf"^{re.escape(claim_num)}\s*\.", chunk):
#             chunk = f"{claim_num}. {chunk}"
#
#         claims.append(chunk)
#
#     return claims
#


def _find_claims_region_tail(text: str) -> Optional[Tuple[int, int, dict]]:
    """
    Find a plausible claims region in the tail of the document using sequential numbering heuristics.
    Returns (start_offset, end_offset, diagnostics) or None.
    """
    if not text:
        return None

    # Restrict to tail to avoid false positives in headers like "... B2 1. SYSTEM ..."
    tail_start = int(len(text) * 0.6)
    tail = text[tail_start:]

    matches = list(_CLAIM_START_MARKER_RX.finditer(tail))
    if len(matches) < 2:
        return None

    # Evaluate candidate windows starting at each match
    best = None
    best_score = -1
    best_diag = {}

    # idx_by_pos = [(m.start(), int(m.group(2))) for m in matches]
    idx_by_pos = [(m.start(), int(m.group(1))) for m in matches]

    for i in range(len(idx_by_pos)):
        pos_i, _ = idx_by_pos[i]
        window_end = min(len(tail), pos_i + 25000)  # deterministic window size
        window = tail[pos_i:window_end]

        # ws = [int(m.group(2)) for m in _CLAIM_START_MARKER_RX.finditer(window)]

        ws = [int(m.group(1)) for m in _CLAIM_START_MARKER_RX.finditer(window)]
        if len(ws) < 5:
            continue

        # sequentiality measure
        seq = 0
        for a, b in zip(ws, ws[1:]):
            if b == a + 1:
                seq += 1

        # Score: prefer more matches and more sequential transitions
        score = len(ws) + 2 * seq

        if score > best_score:
            best_score = score
            best = (tail_start + pos_i, tail_start + window_end)
            best_diag = {
                "tail_start": tail_start,
                "window_start": tail_start + pos_i,
                "window_end": tail_start + window_end,
                "claim_starts_in_window": len(ws),
                "sequential_transitions": seq,
                "score": score,
                "first_numbers": ws[:10],
            }

    if best is None:
        return None

    return best[0], best[1], best_diag


def _extract_claims_block(
    body_text: str,
    sections: Dict[str, str],
    diag: Diagnostics,
) -> tuple[str, str]:
    """
    Extract the best-effort claims block using the recommended cascade:
    1) anchor phrase search
    2) tail numbered-list detection
    3) (optional) section["claims"] if it exists and looks valid
    """
    # 1) Anchor phrase (preferred)
    m = _CLAIMS_ANCHOR_RX.search(body_text)
    if m:
        _diag_info(
            diag,
            "body.claims.anchor_used",
            "Claims extracted using anchor phrase.",
            field="claims",
            meta={"anchor": m.group(1)},
        )
        return body_text[m.end() :].strip(), "anchor"

    # 2) Tail numbered list (fallback)
    tail_region = _find_claims_region_tail(body_text)
    if tail_region:
        start, end, tail_diag = tail_region
        _diag_info(
            diag,
            "body.claims.tail_used",
            "Claims extracted using tail numbered-list heuristic.",
            field="claims",
            meta={"region": {"start": start, "end": end, **tail_diag}},
        )
        return body_text[
            start:
        ].strip(), "tail_numbered_list"  # claims usually run to end

    # 3) Section-based claims (only if present; last resort)
    claims_section = (sections.get("claims") or "").strip()
    if claims_section:
        _diag_info(
            diag,
            "body.claims.section_used",
            "Claims extracted from detected 'claims' section.",
            field="claims",
        )
        return claims_section, "section_claims"

    diag.warn(
        "body.claims.none",
        "No claims block could be extracted.",
        field="claims",
    )
    return "", "none"


# -----------------------------------------------------------------------------
# Figure reference parsing
# -----------------------------------------------------------------------------


# Capture a FIG/FIGS reference followed by a "figlist" chunk that may include:
# - single ids: 1, 2A
# - ranges: 1A-1C, 3-5
# Use common patterns for figure references
# - ranges: 1A-1C
# - lists: 2, 3 and 4
# - mixed: 1A-1C, 2 and 3

# Alias for backwards compatibility
_parse_fig_id = patterns.parse_fig_id


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


def _expand_range(start: str, end: str) -> Iterable[str]:
    if start == end:
        return [start]

    m1 = re.match(r"(\d+)([A-Z]?)", start)
    m2 = re.match(r"(\d+)([A-Z]?)", end)
    if not m1 or not m2:
        return [start, end]

    n1, s1 = m1.groups()
    n2, s2 = m2.groups()

    # Only expand letter suffix ranges like 2A-2C; otherwise return endpoints.
    if n1 != n2 or not s1 or not s2:
        return [start, end]

    if ord(s2) < ord(s1):
        return [start, end]

    return [f"{n1}{chr(c)}" for c in range(ord(s1), ord(s2) + 1)]


# def _extract_figure_ids(text: str) -> List[str]:
#     ids: List[str] = []
#     for m in _FIG_REF_RE.finditer(text):
#         s = m.group(1)
#         e = m.group(2)
#         if e:
#             ids.extend(_expand_range(s, e))
#         else:
#             ids.append(s)
#     return sorted(set(ids))
#

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
    for m in patterns.FIG_REF_RE.finditer(text):
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
    doc: MultiPage,
    diag: Diagnostics,
    policy: PatentBodyPolicy = PatentBodyPolicy(),
    expected_claim_count: int | None = None,
    expected_drawing_count: int | None = None,
) -> PatentBodyData:
    """Parse the patent **body** (non-front-matter) in a diagnostics-first way.

    This function is designed to be called inside a caller-level try/except.

    Expected/normal data quality issues are recorded to `diag` and the function
    returns best-effort structured data.

    Catastrophic failures (e.g., PDF cannot be opened) may still raise.
    """

    from patent_ingest.common import normalize_punctuation_spacing

    body_text = _normalize_text(normalize_punctuation_spacing(doc.linearize()))

    # --- section splitting (position-based) ---
    sections, spans, headings_found = _split_sections_by_heading_positions(body_text)
    if not sections:
        diag.warn(
            "body.no_section_headings_detected",
            "No section headings detected; proceeding with fallback heuristics.",
            field="body",
        )

    # --- drawings descriptions ---
    drawings_text = sections.get("brief_description_of_drawings", "")
    drawings_items = extract_drawing_descriptions(drawings_text)
    drawings_method = "section" if drawings_items else "none"

    if not drawings_items:
        # fallback: try from full body
        drawings_items = extract_drawing_descriptions(body_text)
        if drawings_items:
            drawings_method = "body_fallback"
            diag.warn(
                "body.drawings.fallback_used",
                "Drawing descriptions not found in section; extracted from full body text instead.",
                field="figures",
            )

    _diag_info(
        diag,
        "body.drawings.count",
        "Drawing description items extracted.",
        field="figures",
        meta={"count": len(drawings_items), "method": drawings_method},
    )

    # --- claims start & section trimming ---
    claims_start = _find_claims_start_offset(body_text)
    if claims_start is not None:
        _diag_info(
            diag,
            "body.claims.start_offset",
            "Claims start offset detected.",
            field="claims",
            meta={"claims_start_offset": claims_start},
        )

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
    else:
        diag.warn(
            "body.claims.start_not_found",
            "Could not identify a claims start offset using anchor or tail heuristics.",
            field="claims",
        )

    # Ensure a claims section exists if we have a start
    if claims_start is not None and "claims" not in sections:
        sections["claims"] = body_text[claims_start:].strip()
        spans["claims"] = (claims_start, len(body_text))

    # --- claims extraction cascade ---
    claims_block, claims_method = _extract_claims_block(body_text, sections, diag)
    claims_items = _parse_claims_from_block(claims_block)
    claims_count = len(claims_items)

    if policy.require_claims and claims_count == 0:
        diag.error(
            "body.claims.missing",
            "No claims could be parsed from the body text.",
            field="claims",
        )
    elif claims_count == 0:
        diag.warn(
            "body.claims.empty",
            "No claims could be parsed from the body text.",
            field="claims",
        )

    if expected_claim_count is not None and expected_claim_count != claims_count:
        diag.warn(
            "body.claims.count_mismatch",
            f"Parsed claims count {claims_count} does not match expected {expected_claim_count}.",
            field="claims",
            meta={"expected": expected_claim_count, "actual": claims_count},
        )

    print(f"Extracted {claims_count} claims using method '{claims_method}'.")

    # --- figures referenced ---
    # IMPORTANT: we only want anchors from the "Brief Description of the Drawings" section.
    # Using full body text will pick up FIG references throughout Detailed Description.
    if drawings_items:
        # Prefer the structured table: stable and inherently constrained to the drawings prose.
        figure_ids = sorted(
            {
                f"{row['figure_number']}{row.get('figure_suffix') or ''}".upper()
                for row in drawings_items
                if row.get("figure_number")
            }
        )
        fig_source = f"drawings_items:{drawings_method}"
    else:
        # If we failed to build drawings items, fall back to scanning ONLY the drawings section text.
        figure_ids = _extract_figure_ids(drawings_text)
        fig_source = "drawings_section_text"
    # --- figures referenced in body (FIG. 1, etc.) ---
    # figure_ids = _extract_figure_ids(body_text)
    fig_count = len(figure_ids)

    if expected_drawing_count is not None:
        # tolerant comparison (same behavior as before)
        if abs(fig_count - expected_drawing_count) > max(
            1, expected_drawing_count // 2
        ):
            diag.warn(
                "body.figures.count_inconsistent",
                "Figure reference count differs substantially from expected.",
                field="figures",
                meta={"expected": expected_drawing_count, "actual": fig_count},
            )

    if policy.require_drawings and not drawings_items:
        diag.error(
            "body.drawings.missing",
            "No drawing descriptions could be extracted.",
            field="figures",
        )

    # --- assemble structured data ---
    claims = ClaimsData(
        count=claims_count, items=tuple(claims_items), method=claims_method
    )
    figures = FiguresData(
        figure_reference_count=fig_count,
        figure_ids=tuple(figure_ids),
        items=tuple(drawings_items),
    )

    return PatentBodyData(
        sections=sections,
        section_spans=spans,
        claims=claims,
        figures=figures,
        headings_found=tuple(headings_found),
        meta={
            "drawings_descriptions_method": drawings_method,
        },
    )


def parse_patent_body_fallible(
    *,
    doc: MultiPage,
    policy: PatentBodyPolicy = PatentBodyPolicy(),
    expected_claim_count: int | None = None,
    expected_drawing_count: int | None = None,
) -> PatentBodyResult:
    """Fallible wrapper that never raises for non-catastrophic issues.

    If `parse_patent_body` raises (e.g., PDF open failure), we convert it to an
    error diagnostic and return FAILED with data=None.
    """
    diag = Diagnostics()
    try:
        data = parse_patent_body(
            doc=doc,
            diag=diag,
            policy=policy,
            expected_claim_count=expected_claim_count,
            expected_drawing_count=expected_drawing_count,
        )
    except Exception as e:
        diag.error(
            "body.exception",
            f"Unhandled exception during body parsing: {e}",
            field="body",
        )
        return PatentBodyResult(
            status=PatentBodyStatus.FAILED,
            data=None,
            diagnostics=diag,
            meta={},
        )

    # Status determination
    if getattr(diag, "errors", None) and diag.errors:
        status = (
            PatentBodyStatus.FAILED
            if policy.fail_on_error
            else PatentBodyStatus.PARTIAL
        )
    elif getattr(diag, "warnings", None) and diag.warnings:
        status = PatentBodyStatus.PARTIAL
    else:
        status = PatentBodyStatus.OK

    return PatentBodyResult(
        status=status,
        data=data,
        diagnostics=diag,
        meta={},
    )
