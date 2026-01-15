from dataclasses import dataclass
from typing import Any, Optional
import re

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Where, Column, Position, Span
from patent_ingest.model.mapping import (
    linearize,
    trim_global_range,
    global_range_to_where,
)
from patent_ingest.parsed import (
    ParsedRaw,
    EntityKind,
    INIDKind,
    ParsedNorm,
    kind_display,
    Kind,
)
from patent_ingest.front_matter.util import (
    normalize_whitespace_basic,
    normalize_punctuation_spacing,
)


@dataclass(frozen=True)
class Inventor:
    name: Optional[str]
    normalized_name: Optional[str]
    location: Optional[str] = None


INVENTOR_SPLIT_PAT = re.compile(r"\s*;\s*")
LOCATION_IN_PARENS_PAT = re.compile(r"\(([^)]+)\)\s*$")

INVENTORS_TRAILING_HEADER_PAT = re.compile(
    r"\(\s*[A-Z]{2}\s*\)\s*Inventors?\s*:\s*$",
    re.IGNORECASE,
)
INVENTORS_EMBEDDED_HEADER_PAT = re.compile(
    r"\(\s*[A-Z]{2}\s*\)\s*Inventors?\s*:.*$",
    re.IGNORECASE,
)
INVENTORS_STRAY_LABEL_PAT = re.compile(
    r"\bInventors?\s*:\s*.*$",
    re.IGNORECASE,
)

INVENTOR_HEADING_STOP_PAT = re.compile(
    r"\b("
    r"U\.S\.\s*PATENT\s*DOCUMENTS|"
    r"FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS|"
    r"REFERENCES\s+CITED|"
    r"ABSTRACT|"
    r"Primary\s+Examiner|"
    r"Assistant\s+Examiner"
    r")\b",
    re.IGNORECASE,
)

REFS_DATE_LINE_PAT = re.compile(r"\b\d{1,2}\s*/\s*\d{4}\b", re.IGNORECASE)
COUNTRY_TAG_THEN_REFS_DATE_PAT = re.compile(
    r"\(\s*[A-Z]{2}\s*\)\s*\d{1,2}\s*/\s*\d{4}\b",
    re.IGNORECASE,
)
COUNTRY_TAG_PAT = re.compile(r"\(\s*[A-Z]{2}\s*\)\s*$")


def normalize_entity_name(name: str) -> str:
    # Use your existing helpers if present; otherwise conservative fallbacks
    try:
        n = normalize_punctuation_spacing(normalize_whitespace_basic(name))
    except NameError:
        n = " ".join(name.split())
    n = n.replace("’", "'").replace("–", "-").replace("—", "-")
    n = re.sub(r"[,\.;:\s]+$", "", n)
    return n


def split_name_and_location(raw: str) -> dict[str, Optional[str]]:
    try:
        raw_clean = normalize_whitespace_basic(raw)
        raw_clean = normalize_punctuation_spacing(raw_clean)
    except NameError:
        raw_clean = " ".join(raw.split())

    m = LOCATION_IN_PARENS_PAT.search(raw_clean)
    if m:
        loc = m.group(1).strip()
        nm = raw_clean[: m.start()].strip()
    else:
        loc = None
        nm = raw_clean.strip()

    nm = nm or None
    loc = loc or None
    return {"name": nm, "location": loc}


def parse_inventor_chunks(raw_inventors_text: str) -> list[tuple[str, Inventor]]:
    """
    Returns list of (raw_chunk, Inventor(value)).
    """
    raw_inventors_text = raw_inventors_text or ""
    chunks = [
        c.strip() for c in INVENTOR_SPLIT_PAT.split(raw_inventors_text) if c.strip()
    ]

    out: list[tuple[str, Inventor]] = []
    for c in chunks:
        parts = split_name_and_location(c)
        nm = parts["name"]
        out.append(
            (
                c,
                Inventor(
                    name=nm,
                    normalized_name=normalize_entity_name(nm) if nm else None,
                    location=parts["location"],
                ),
            )
        )
    return out


def _strip_leading_label(s: str, labels: list[str]) -> str:
    if not s:
        return s
    ss = s.lstrip()
    for lab in labels:
        if ss.lower().startswith(lab.lower()):
            cut = ss[len(lab) :]
            return cut.lstrip(" :\t\r\n-")
    return s


INID_ANY_MARKER_PAT = re.compile(r"\(\s*\d{2}\s*\)")


def _clean_inventors_text(raw: str) -> str:
    raw = _strip_leading_label(raw or "", ["Inventors", "Inventor"]).strip()

    # NEW: stop at the next INID marker (73, 21, 22, 65, 51, 10, 45, etc.)
    m_inid = INID_ANY_MARKER_PAT.search(raw)
    if m_inid:
        raw = raw[: m_inid.start()].strip()

    # Existing stops
    m_h = INVENTOR_HEADING_STOP_PAT.search(raw)
    if m_h:
        raw = raw[: m_h.start()].strip()

    m_bd = COUNTRY_TAG_THEN_REFS_DATE_PAT.search(raw)
    if m_bd:
        raw = raw[: m_bd.start()].strip()

    m_d = REFS_DATE_LINE_PAT.search(raw)
    if m_d:
        raw = raw[: m_d.start()].strip()

    raw = COUNTRY_TAG_PAT.sub("", raw).strip()

    raw = INVENTORS_EMBEDDED_HEADER_PAT.sub("", raw).strip()
    raw = INVENTORS_STRAY_LABEL_PAT.sub("", raw).strip()
    raw = INVENTORS_TRAILING_HEADER_PAT.sub("", raw).strip()

    return raw


def _find_chunk_span_in_text(
    haystack: str, needle: str, start_at: int
) -> Optional[tuple[int, int, int]]:
    """
    Find needle in haystack at/after start_at. Returns (start,end,next_start) or None.
    next_start is end to allow sequential searching.
    """
    if not needle:
        return None
    i = haystack.find(needle, start_at)
    if i < 0:
        return None
    return i, i + len(needle), i + len(needle)


def _shift_where_for_subslice(
    raw_where: Where, subslice: tuple[int, int]
) -> tuple[Where, dict[str, Any]]:
    """
    Convert a substring slice within raw.text into a refined Where when possible.
    Only refines for Span.
    """
    s, e = subslice
    meta = {"refine": {"start_idx": s, "end_idx": e}}
    if isinstance(raw_where, Span):
        new_start = Position(
            raw_where.start.page, raw_where.start.column, raw_where.start.offset + s
        )
        new_end = Position(
            raw_where.end.page, raw_where.end.column, raw_where.start.offset + e
        )
        return Span(new_start, new_end), meta
    return raw_where, meta


INVENTORS_LABEL_FALLBACK_PAT = re.compile(r"(?is)\bInventors?\s*[:\-]\s*(.+)")


def _fallback_inventors_label_block(
    doc: MultiPage,
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedRaw[str]]:
    linear_text, segments = linearize(doc, sep=sep, order=order)
    m = INVENTORS_LABEL_FALLBACK_PAT.search(linear_text)
    if not m:
        return None
    g_start, g_end = m.span(1)

    # Trim the captured group
    g_start, g_end = trim_global_range(linear_text, g_start, g_end)
    where = global_range_to_where(g_start, g_end, segments)

    return ParsedRaw[
        str
    ](
        kind=EntityKind.INVENTOR,  # will retag to inventor later
        where=where,
        text=linear_text[g_start:g_end],
        confidence=0.25,
        meta={
            "source": "fallback",
            "rule": "inventors:label-search",
            "global": (g_start, g_end),
        },
    )


def extract_inventors(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> list[ParsedNorm[Inventor]]:
    """
    New-model inventors extractor. One-to-many.

    Source precedence:
      1) INID(72)
      2) INID(75)
      3) fallback label search "Inventors: ..."

    Returns list[ParsedNorm[Inventor]] (possibly empty).
    """
    # 1) choose source
    src: Optional[ParsedRaw[str]] = None
    src_code: Optional[str] = None
    src_kind: Optional[Kind] = None

    inid72 = inid_blocks.get(INIDKind._72) if hasattr(INIDKind, "_72") else None
    inid75 = inid_blocks.get(INIDKind._75) if hasattr(INIDKind, "_75") else None

    if inid72 and (inid72.text or "").strip():
        src = inid72
        src_code = "72"
        src_kind = INIDKind._72
    elif inid75 and (inid75.text or "").strip():
        src = inid75
        src_code = "75"
        src_kind = INIDKind._75
    else:
        src = _fallback_inventors_label_block(doc, sep=sep, order=order)
        src_code = None
        src_kind = EntityKind.INVENTOR  # placeholder

    if not src or not (src.text or "").strip():
        return []

    # 2) clean the overall block
    cleaned_block_text = _clean_inventors_text(src.text)
    if not cleaned_block_text:
        return []

    # Prepare a “block raw” we can use for refinement
    block_raw = ParsedRaw[str](
        kind=EntityKind.INVENTOR,  # block-level kind; individuals become PERSON
        where=src.where,
        text=cleaned_block_text,
        confidence=src.confidence,
        meta={
            **src.meta,
            "source_inid_code": src_code,
            "source_kind": kind_display(src.kind),
        },
    )

    # 3) split into inventor chunks + parse
    chunk_pairs = parse_inventor_chunks(cleaned_block_text)
    if not chunk_pairs:
        return []

    # 4) Produce per-inventor ParsedNorm[Inventor], with per-chunk where where possible
    out: list[ParsedNorm[Inventor]] = []
    search_pos = 0
    for raw_chunk, inventor_val in chunk_pairs:
        # Attempt to refine per-inventor spans by locating the chunk in the cleaned block text
        subslice = _find_chunk_span_in_text(cleaned_block_text, raw_chunk, search_pos)
        if subslice:
            s, e, search_pos = subslice
            where2, refine_meta = _shift_where_for_subslice(block_raw.where, (s, e))
        else:
            where2, refine_meta = (
                block_raw.where,
                {"refine": None, "note": "could not locate chunk in block"},
            )

        # Each inventor as its own parsed+normalized entity
        inventor_raw = ParsedRaw[str](
            kind=EntityKind.INVENTOR,
            where=where2,
            text=raw_chunk,
            confidence=block_raw.confidence,
            meta={
                **block_raw.meta,
                **refine_meta,
                "rule": "inventors:split-by-semicolon",
                "role": "inventor",
                "source": src.meta.get("source", "inid"),
                "inid_code": src_code,
            },
        )

        out.append(
            inventor_raw.normalize_to(
                value=inventor_val,
                kind=EntityKind.INVENTOR,  # keep as PERSON, store role in meta
                system="PDF",
                rule="inventors:normalize",
                normalized=True,
                role="inventor",
                inid_code=src_code,
            )
        )

    return out
