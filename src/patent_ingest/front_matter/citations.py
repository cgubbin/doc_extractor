from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union, Literal
import re


# =============================================================================
# Document model
# =============================================================================


class Column(Enum):
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True)
class TwoColumn:
    left: str
    right: str


@dataclass(frozen=True)
class MultiPage:
    pages: List[TwoColumn]

    def get_column_text(self, page: int, column: Column) -> str:
        p = self.pages[page]
        return p.left if column is Column.LEFT else p.right


# =============================================================================
# Span model
# =============================================================================


@dataclass(frozen=True, order=True)
class Position:
    page: int
    column: Column
    offset: int


@dataclass(frozen=True)
class Span:
    """Half-open [start, end), must be within one (page, column)."""

    start: Position
    end: Position

    def __post_init__(self) -> None:
        if (self.start.page, self.start.column) != (self.end.page, self.end.column):
            raise ValueError(
                "Span must be within one page+column; use MultiSpan for cross boundaries."
            )
        if self.end.offset < self.start.offset:
            raise ValueError("Span end must be >= start.")


@dataclass(frozen=True)
class MultiSpan:
    parts: Tuple[Span, ...]


Where = Union[Span, MultiSpan]


def _span_sort_key(s: Span) -> Tuple[int, int, int, int]:
    col_ord = 0 if s.start.column is Column.LEFT else 1
    return (s.start.page, col_ord, s.start.offset, s.end.offset)


def coalesce_spans(spans: Sequence[Span]) -> List[Span]:
    if not spans:
        return []
    spans_sorted = sorted(spans, key=_span_sort_key)
    out: List[Span] = []
    cur = spans_sorted[0]
    for s in spans_sorted[1:]:
        same_seg = (s.start.page, s.start.column) == (cur.start.page, cur.start.column)
        if same_seg and s.start.offset <= cur.end.offset:
            new_end = Position(
                cur.end.page, cur.end.column, max(cur.end.offset, s.end.offset)
            )
            cur = Span(cur.start, new_end)
        else:
            out.append(cur)
            cur = s
    out.append(cur)
    return out


def merge_where(a: Where, b: Where) -> Where:
    parts: List[Span] = []
    parts.extend(a.parts if isinstance(a, MultiSpan) else (a,))
    parts.extend(b.parts if isinstance(b, MultiSpan) else (b,))
    parts = coalesce_spans(parts)
    return parts[0] if len(parts) == 1 else MultiSpan(parts=tuple(parts))


# =============================================================================
# Parsed containers
# =============================================================================


@dataclass(frozen=True)
class ParsedRaw:
    kind: str
    where: Where
    text: str
    confidence: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def normalize_to(
        self, value: Any, *, kind: Optional[str] = None, **meta_updates: Any
    ) -> "ParsedNorm":
        meta = dict(self.meta)
        meta.update(meta_updates)
        return ParsedNorm(
            kind=kind or self.kind,
            where=self.where,
            raw_text=self.text,
            value=value,
            confidence=self.confidence,
            meta=meta,
        )


@dataclass(frozen=True)
class ParsedNorm:
    kind: str
    where: Where
    raw_text: str
    value: Any
    confidence: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Linearization + mapping
# =============================================================================


@dataclass(frozen=True)
class Segment:
    page: int
    column: Column
    text: str
    global_start: int
    global_end: int


def linearize(
    doc: MultiPage,
    *,
    sep: str = "\n",
    order: Tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Tuple[str, List[Segment]]:
    segments: List[Segment] = []
    chunks: List[str] = []
    cursor = 0
    for pageno, page in enumerate(doc.pages):
        for col in order:
            txt = page.left if col is Column.LEFT else page.right
            chunks.append(txt)
            segments.append(
                Segment(
                    page=pageno,
                    column=col,
                    text=txt,
                    global_start=cursor,
                    global_end=cursor + len(txt),
                )
            )
            cursor += len(txt)
            chunks.append(sep)  # no provenance
            cursor += len(sep)
    return "".join(chunks), segments


def trim_global_range(text: str, start: int, end: int) -> Tuple[int, int]:
    s, e = start, end
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def global_range_to_where(
    global_start: int, global_end: int, segments: List[Segment]
) -> Where:
    parts: List[Span] = []
    for seg in segments:
        a = max(global_start, seg.global_start)
        b = min(global_end, seg.global_end)
        if b <= a:
            continue
        s = Position(seg.page, seg.column, a - seg.global_start)
        e = Position(seg.page, seg.column, b - seg.global_start)
        parts.append(Span(s, e))
    if not parts:
        raise ValueError(
            "Global range did not overlap any segment (maybe only separators)."
        )
    parts = coalesce_spans(parts)
    return parts[0] if len(parts) == 1 else MultiSpan(parts=tuple(parts))


# =============================================================================
# Citation value types
# =============================================================================

CitationType = Literal["US_GRANT", "US_PUBAPP"]


@dataclass(frozen=True)
class CitationId:
    type: CitationType
    canonical: str  # "5864394" or "20010043333"
    display: str  # "5,864,394" or "2001/0043333 A1"
    kind_code: Optional[str] = None


# =============================================================================
# Patterns
# =============================================================================

REFS_START_PAT = re.compile(r"\(\s*56\s*\)\s*References\s*Cited\b", re.IGNORECASE)
REFS_WORDS_PAT = re.compile(r"\bReferences\s*Cited\b", re.IGNORECASE)

US_PAT_DOCS_PAT = re.compile(r"\bU\.S\.\s*PATENT\s*DOCUMENTS\b", re.IGNORECASE)
FOREIGN_PAT_DOCS_PAT = re.compile(r"\bFOREIGN\s+PATENT\s+DOCUMENTS\b", re.IGNORECASE)
OTHER_PUBS_PAT = re.compile(r"\bOTHER\s+PUBLICATIONS\b", re.IGNORECASE)

ABSTRACT_PAT = re.compile(r"\(\s*57\s*\)\s*ABSTRACT\b", re.IGNORECASE)

REFS_EVIDENCE_PAT = re.compile(
    r"\b("
    r"U\.S\.\s*PATENT\s*DOCUMENTS|"
    r"FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS|"
    r"\(\s*56\s*\)\s*References\s+Cited|"
    r"References\s+Cited"
    r")\b",
    re.IGNORECASE,
)

# Evidence: citations-looking tokens
US_GRANT_EVIDENCE_PAT = re.compile(r"\b\d{1,2}\s*[,\.]\s*\d{3}\s*[,\.]\s*\d{3}\b")
US_PUB_EVIDENCE_PAT = re.compile(
    r"\b(?:19|20)\d{2}\s*[/\.\u2044\u2215\uFF0F]\s*[0-9O][0-9O,\s\.]{5,12}\s*A\d",
    re.IGNORECASE,
)

# US grant citations: strict grouped form
US_PATENT_GROUPED_PAT = re.compile(r"\b(\d{1,2})\s*[,\.]\s*(\d{3})\s*[,\.]\s*(\d{3})\b")

# US published applications: your robust pattern
US_PUB_APP_PAT = re.compile(
    r"""
    \b((?:19|20)\d{2})                         # year
    \s*[/\.\u2044\u2215\uFF0F]\s*              # separator: / or . or unicode slashes
    ([0-9O][0-9O,\s\.]{5,12})                  # serial-ish (may contain commas/spaces/dots; may have O)
    \s*
    (A\d|A9|B\d)                               # kind code REQUIRED
    \s*[*†]?                                   # optional star/dagger
    (?=                                       # allow immediate date run-in or whitespace/end
        \s|$|[^\w]|
        \d{1,2}\s*[/\.\u2044\u2215\uFF0F]\s*(?:19|20)\d{2}
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Related-app block removal/masking
RELATED_APP_HEAD_PAT = re.compile(
    r"\bRelated\s+U\.S\.\s+Application\s+Data\b", re.IGNORECASE
)
RELATED_APP_END_PAT = re.compile(
    r"\b("
    r"\(\s*56\s*\)\s*References\s+Cited|"
    r"References\s+Cited|"
    r"U\.S\.\s*PATENT\s*DOCUMENTS|"
    r"FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS|"
    r"Primary\s+Examiner|"
    r"\(\s*57\s*\)\s*ABSTRACT"
    r")\b",
    re.IGNORECASE,
)

# Narrative prose guard (prevents extracting “Pat. No.” in continuation paragraphs)
NARRATIVE_CONTEXT_PAT = re.compile(
    r"(?i)\b(?:pat\.?\s*no\.?|application\s+no\.?|continuation(?:-in-part)?\s+of|now\s+abandoned)\b"
)

# Foreign prefix context guard for US pub-app matches
FOREIGN_PREFIXES = (
    "WO",
    "WIPO",
    "EP",
    "EPO",
    "PCT",
    "KR",
    "JP",
    "CN",
    "DE",
    "FR",
    "GB",
    "UK",
    "CA",
    "TW",
    "RU",
    "BR",
    "IN",
    "AU",
    "IT",
    "ES",
    "NL",
    "SE",
    "CH",
)
_GLUE = r"[\s\(\)\[\]\{\}:;,\.\-–—/]*"
FOREIGN_PREFIX_BEFORE_YEAR_PAT = re.compile(
    rf"(?:^|[\s\(\[\{{])"
    rf"({'|'.join(map(re.escape, FOREIGN_PREFIXES))})"
    rf"{_GLUE}$",
    re.IGNORECASE,
)


# =============================================================================
# Normalization helpers (span-safe: length-preserving)
# =============================================================================


def normalize_separators_for_refs(text: str) -> str:
    """Normalize unicode slashes to ASCII '/', preserving length."""
    if not text:
        return ""
    return (
        text.replace("\u2044", "/")  # ⁄
        .replace("\u2215", "/")  # ∕
        .replace("\uff0f", "/")  # ／
    )


def fix_common_ocr_al_to_a1(text: str) -> str:
    """Fix OCR 'Al' -> 'A1' (same length) in a few common cases."""
    return (text or "").replace("Al", "A1").replace("aI", "A1").replace("AI", "A1")


def normalize_us_pub_app(year: str, serial_raw: str) -> Optional[str]:
    """
    Canonicalize US published app: YYYY + 7 digits (zfilled), digits-only.
    Handles O->0 and drops commas/spaces/dots.
    """
    if not year or not serial_raw:
        return None

    s = serial_raw.upper().replace("O", "0")
    s = re.sub(r"[,\s]+", "", s)
    s = re.sub(r"\D", "", s)

    if len(s) < 6 or len(s) > 8:
        return None
    if len(s) < 7:
        s = s.zfill(7)
    return f"{year}{s}"


def comma_format_us_patent(digits: str) -> str:
    d = re.sub(r"\D", "", digits or "")
    if not d:
        return ""
    try:
        return f"{int(d):,}"
    except ValueError:
        return d


# =============================================================================
# Context filters
# =============================================================================


def is_foreign_publication_context(text: str, match_start: int) -> bool:
    """
    True if a foreign authority prefix (WO/EP/JP/...) appears immediately before the YYYY/serial token.
    """
    window_start = max(0, match_start - 24)
    prefix_window = text[window_start:match_start].upper()
    prefix_window = re.sub(r"\s+", " ", prefix_window)
    return bool(FOREIGN_PREFIX_BEFORE_YEAR_PAT.search(prefix_window))


def is_narrative_context(text: str, match_start: int) -> bool:
    """
    True if the token looks like it's part of a continuation/narrative paragraph rather than a refs row.
    """
    window_start = max(0, match_start - 60)
    window = text[window_start:match_start]
    return bool(NARRATIVE_CONTEXT_PAT.search(window))


# =============================================================================
# Related-app block removal/masking
# =============================================================================


def strip_related_application_data_block(text: str) -> str:
    """
    Evidence filter: remove the 'Related U.S. Application Data' paragraph(s) only (length-changing OK).
    """
    if not text:
        return ""
    m = RELATED_APP_HEAD_PAT.search(text)
    if not m:
        return text

    start = m.start()
    m_end = RELATED_APP_END_PAT.search(text, m.end())
    if not m_end:
        end = min(len(text), m.end() + 1200)
        return (text[:start] + "\n" + text[end:]).strip()

    end = m_end.start()
    return (text[:start] + "\n" + text[end:]).strip()


def mask_related_application_data_block_same_length(text: str) -> str:
    """
    Extraction safety: mask the Related App Data block with same-length whitespace/newlines,
    preserving offsets for span mapping while preventing regex hits inside the block.
    """
    if not text:
        return ""
    m = RELATED_APP_HEAD_PAT.search(text)
    if not m:
        return text

    start = m.start()
    m_end = RELATED_APP_END_PAT.search(text, m.end())
    if not m_end:
        end = min(len(text), m.end() + 1200)
    else:
        end = m_end.start()

    block = text[start:end]
    masked = "".join("\n" if ch == "\n" else " " for ch in block)
    return text[:start] + masked + text[end:]


# =============================================================================
# References region builder (start on page 0 OR later; continue until evidence stops)
# =============================================================================


@dataclass(frozen=True)
class RegionPiece:
    local_start: int
    local_end: int
    global_start: int
    global_end: int


@dataclass(frozen=True)
class ReferencesRegion:
    text: str
    pieces: Tuple[RegionPiece, ...]
    where: Optional[Where]
    pages_used: Tuple[int, ...]


def _refs_start_in_page_global(
    linear_text: str, segments: List[Segment], page: int
) -> Optional[int]:
    """
    Earliest usable refs anchor within a page window, returned as global offset into linear_text.
    """
    page_segs = [s for s in segments if s.page == page]
    if not page_segs:
        return None

    win_start = min(s.global_start for s in page_segs)
    win_end = max(s.global_end for s in page_segs)
    page_text = linear_text[win_start:win_end]

    candidates: List[int] = []
    for pat in (
        REFS_START_PAT,
        REFS_WORDS_PAT,
        US_PAT_DOCS_PAT,
        FOREIGN_PAT_DOCS_PAT,
        OTHER_PUBS_PAT,
    ):
        m = pat.search(page_text)
        if m:
            candidates.append(win_start + m.start())
    return min(candidates) if candidates else None


def build_references_region(
    doc: MultiPage,
    *,
    # If max_pages is None, we scan forward up to scan_limit pages from the start.
    max_pages: Optional[int] = None,
    scan_limit: int = 10,
    sep: str = "\n",
    order: Tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> ReferencesRegion:
    """
    Assemble a references region that may start on page 0 OR later pages.

    Strategy:
      - Find earliest page with refs anchor within the scan cap.
      - Start page: slice from anchor to ABSTRACT if present on same page; else to end of page.
      - Continue adding subsequent pages while they show refs evidence (headings or citation-like numbers).
      - STOP at first non-evidence page after at least one continuation page was included.

    Returned region.text is SAFE for matching:
      - Related-app blocks are SAME-LENGTH masked on continuation pages (and optionally on start page too),
        preventing narrative Pat./Application numbers from being extracted.
    """
    linear_text, segments = linearize(doc, sep=sep, order=order)
    n_pages = len(doc.pages)

    cap = n_pages
    if max_pages is not None:
        cap = min(cap, max_pages)
    cap = min(cap, scan_limit)

    # 1) Find start page anywhere within cap
    start_page: Optional[int] = None
    start_global: Optional[int] = None
    for p in range(cap):
        s = _refs_start_in_page_global(linear_text, segments, p)
        if s is not None:
            start_page = p
            start_global = s
            break

    if start_page is None or start_global is None:
        return ReferencesRegion(text="", pieces=tuple(), where=None, pages_used=tuple())

    def _page_window(page_i: int) -> Tuple[int, int, str]:
        page_segs = [s for s in segments if s.page == page_i]
        if not page_segs:
            return (0, 0, "")
        win_start = min(s.global_start for s in page_segs)
        win_end = max(s.global_end for s in page_segs)
        return win_start, win_end, linear_text[win_start:win_end]

    pieces: List[RegionPiece] = []
    chunks: List[str] = []
    pages_used: List[int] = []
    local_cursor = 0

    # 2) Start page slice
    win_start, win_end, page_text = _page_window(start_page)

    page_slice = linear_text[start_global:win_end]
    m_abs = ABSTRACT_PAT.search(page_slice)
    end_global = (
        start_global + m_abs.start() if (m_abs and m_abs.start() > 0) else win_end
    )

    t0s, t0e = trim_global_range(linear_text, start_global, end_global)

    # Mask related-app block on the start page slice too (safe and prevents narrative extraction)
    start_chunk = mask_related_application_data_block_same_length(linear_text[t0s:t0e])
    chunks.append(start_chunk)
    pieces.append(
        RegionPiece(
            local_start=0, local_end=len(start_chunk), global_start=t0s, global_end=t0e
        )
    )
    local_cursor += len(start_chunk)
    pages_used.append(start_page)

    # 3) Continuation pages: include while evidence continues
    included_any_continuation = False

    for page_i in range(start_page + 1, cap):
        p_start, p_end, p_text = _page_window(page_i)
        if not p_text.strip():
            if included_any_continuation:
                break
            continue

        p_text2 = strip_related_application_data_block(p_text)
        has_heading = bool(REFS_EVIDENCE_PAT.search(p_text2))
        has_numbers = bool(
            US_GRANT_EVIDENCE_PAT.search(p_text2) or US_PUB_EVIDENCE_PAT.search(p_text2)
        )
        is_refs_page = has_heading or has_numbers

        if not is_refs_page:
            if included_any_continuation:
                break
            continue

        included_any_continuation = True

        # Local-only separator between pages
        sep2 = "\n\n"
        chunks.append(sep2)
        local_cursor += len(sep2)

        ts, te = trim_global_range(linear_text, p_start, p_end)
        chunk = mask_related_application_data_block_same_length(linear_text[ts:te])

        start_local = local_cursor
        chunks.append(chunk)
        pieces.append(
            RegionPiece(
                local_start=start_local,
                local_end=start_local + len(chunk),
                global_start=ts,
                global_end=te,
            )
        )
        local_cursor += len(chunk)
        pages_used.append(page_i)

    # 4) Merge wheres for region coverage
    region_text = "".join(chunks)
    region_where: Optional[Where] = None
    for p in pieces:
        w = global_range_to_where(p.global_start, p.global_end, segments)
        region_where = w if region_where is None else merge_where(region_where, w)

    return ReferencesRegion(
        text=region_text,
        pieces=tuple(pieces),
        where=region_where,
        pages_used=tuple(pages_used),
    )


# =============================================================================
# Local->Where mapping for matches inside region.text
# =============================================================================


def local_span_to_where(
    local_start: int,
    local_end: int,
    pieces: Tuple[RegionPiece, ...],
    segments: List[Segment],
) -> Where:
    spans: List[Span] = []
    for p in pieces:
        a = max(local_start, p.local_start)
        b = min(local_end, p.local_end)
        if b <= a:
            continue
        g_a = p.global_start + (a - p.local_start)
        g_b = p.global_start + (b - p.local_start)
        w = global_range_to_where(g_a, g_b, segments)
        spans.extend(w.parts if isinstance(w, MultiSpan) else (w,))
    spans = coalesce_spans(sorted(spans, key=_span_sort_key))
    return spans[0] if len(spans) == 1 else MultiSpan(parts=tuple(spans))


# =============================================================================
# Citation extraction
# =============================================================================


def extract_citations(
    doc: MultiPage,
    *,
    max_pages: Optional[int] = None,
    scan_limit: int = 10,
    sep: str = "\n",
    order: Tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
    own_patent_digits: Optional[str] = None,  # exclude self-citation for grants
    exclude_pubapp_canonicals: Optional[set[str]] = None,
) -> List[ParsedNorm]:
    """
    Extract US grant + US published application citations from the references region.

    Returns list[ParsedNorm] with value= CitationId.

    Guardrails:
      - foreign prefixes (WO/EP/JP/...) are excluded for pub-app matches
      - narrative continuation/related-app prose is excluded for both grants and pubapps
      - related-app blocks are masked in the region builder to prevent matches inside them
    """
    exclude_pubapp_canonicals = exclude_pubapp_canonicals or set()

    # We need segments for mapping. linear_text is not used directly here.
    _linear_text, segments = linearize(doc, sep=sep, order=order)

    region = build_references_region(
        doc, max_pages=max_pages, scan_limit=scan_limit, sep=sep, order=order
    )
    if not region.text.strip():
        return []

    # Span-safe normalization (length-preserving)
    t = normalize_separators_for_refs(region.text)
    t = fix_common_ocr_al_to_a1(t)

    out: List[ParsedNorm] = []
    seen: set[tuple[str, str]] = set()  # (type, canonical)

    # ---- US grants (grouped) ----
    for m in US_PATENT_GROUPED_PAT.finditer(t):
        if is_narrative_context(t, m.start()):
            continue

        digits = f"{m.group(1)}{m.group(2)}{m.group(3)}"
        if own_patent_digits and digits == own_patent_digits:
            continue
        key = ("US_GRANT", digits)
        if key in seen:
            continue
        seen.add(key)

        loc_s, loc_e = m.span(0)
        where = local_span_to_where(loc_s, loc_e, region.pieces, segments)
        display = comma_format_us_patent(digits)
        value = CitationId(type="US_GRANT", canonical=digits, display=display)

        raw = ParsedRaw(
            kind="CITATION_ID",
            where=where,
            text=t[loc_s:loc_e],
            confidence=0.55,
            meta={
                "source": "refs-region",
                "rule": "citations:us-grant-grouped",
                "pages_used": region.pages_used,
            },
        )
        out.append(raw.normalize_to(value=value, kind="CITATION_ID", normalized=True))

    # ---- US published applications ----
    for m in US_PUB_APP_PAT.finditer(t):
        if is_foreign_publication_context(t, m.start()):
            continue
        if is_narrative_context(t, m.start()):
            continue

        year = m.group(1)
        serial_raw = m.group(2)
        kind_code = (m.group(3) or "").upper()

        canon = normalize_us_pub_app(year, serial_raw)
        if not canon:
            continue
        if canon in exclude_pubapp_canonicals:
            continue

        key = ("US_PUBAPP", canon)
        if key in seen:
            continue
        seen.add(key)

        loc_s, loc_e = m.span(0)
        where = local_span_to_where(loc_s, loc_e, region.pieces, segments)

        serial_digits = re.sub(r"\D", "", serial_raw.upper().replace("O", "0"))
        if len(serial_digits) < 7:
            serial_digits = serial_digits.zfill(7)
        display = f"{year}/{serial_digits} {kind_code}".strip()

        value = CitationId(
            type="US_PUBAPP", canonical=canon, display=display, kind_code=kind_code
        )

        raw = ParsedRaw(
            kind="CITATION_ID",
            where=where,
            text=t[loc_s:loc_e],
            confidence=0.55,
            meta={
                "source": "refs-region",
                "rule": "citations:us-pubapp",
                "pages_used": region.pages_used,
            },
        )
        out.append(raw.normalize_to(value=value, kind="CITATION_ID", normalized=True))

    return out
