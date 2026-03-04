from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from doc_extractor.body.claims import Claim, claims_from_chunks, validate_claims
from doc_extractor.diagnostics import Diagnostics
from doc_extractor.model.analysis import BodyResult

from doc_extractor.body.headings import normalize_section_heading
from doc_extractor.body.patterns import (
    extract_drawing_descriptions,
    _extract_figure_ids,
    # _find_claims_start_offset,
    _parse_claims_from_block,
)

# -----------------------------------------------------------------------------
# Fallible result types (same as before)
# -----------------------------------------------------------------------------


class PatentBodyStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class PatentBodyPolicy:
    require_claims: bool = True
    require_drawings: bool = False
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
    sections: Dict[str, str]
    section_spans: Dict[str, Tuple[int, int]]  # char offsets in linearized text
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
        return list(self.figures.items)


@dataclass(frozen=True)
class PatentBodyResult:
    status: PatentBodyStatus
    data: Optional[PatentBodyData]
    diagnostics: Diagnostics
    meta: Dict[str, Any] = field(default_factory=dict)


def _diag_info(diag: Diagnostics, code: str, message: str, **kwargs: Any) -> None:
    if hasattr(diag, "info_msg"):
        diag.info_msg(code, message, **kwargs)
    elif hasattr(diag, "info"):
        diag.info(code, message, **kwargs)


# -----------------------------------------------------------------------------
# Block model adapter (keeps this module decoupled from your analysis models)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _BodyBlock:
    kind: str
    text: str
    page: int = -1
    col: Optional[str] = None


def _iter_body_blocks(body: BodyResult) -> Iterable[_BodyBlock]:
    for b in body.blocks:
        kind = b.kind
        if kind == "section_heading":
            kind2 = "heading"
        elif kind == "paragraph":
            kind2 = "paragraph"
        else:
            kind2 = "paragraph"  # enumerator/para_marker treated as paragraph or skip
        yield _BodyBlock(kind=kind2, text=b.text or "", page=b.page, col=b.col)


# -----------------------------------------------------------------------------
# Linearization from blocks (stable offsets + spans)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Linearized:
    text: str
    # per-block char span in the linearized text
    spans: List[Tuple[int, int, _BodyBlock]]


def _linearize_blocks(blocks: Sequence[_BodyBlock]) -> _Linearized:
    parts: List[str] = []
    spans: List[Tuple[int, int, _BodyBlock]] = []
    cursor = 0

    for b in blocks:
        t = (b.text or "").strip()
        if not t:
            continue

        # separate blocks with a double newline for readability
        if parts:
            parts.append("\n\n")
            cursor += 2

        start = cursor
        parts.append(t)
        cursor += len(t)
        end = cursor
        spans.append((start, end, b))

    return _Linearized("".join(parts), spans)


# -----------------------------------------------------------------------------
# Section construction from heading blocks
# -----------------------------------------------------------------------------


def _sections_from_blocks(
    lin: _Linearized,
    diag: Diagnostics,
) -> Tuple[Dict[str, str], Dict[str, Tuple[int, int]], List[dict]]:
    """
    Construct sections using heading/subheading blocks.
    Spans are char offsets into lin.text.
    """
    headings_found: List[dict] = []

    # Identify section boundary blocks in order
    markers: List[Tuple[str, int]] = []  # (section_key, char_start)

    for start, end, b in lin.spans:
        if b.kind not in {"heading", "subheading", "section_heading"}:
            continue

        key = normalize_section_heading(b.text)
        if key:
            markers.append((key.value, start))
            headings_found.append(
                {"section": key, "text": b.text.strip(), "page": b.page, "col": b.col}
            )
        else:
            diag.warn(
                "body.unrecognized_heading",
                f"Heading block not matched to any section key: {b.text!r}",
                field="body",
                meta={"text": b.text.strip(), "kind": b.kind, "page": b.page},
            )

    if not markers:
        return {}, {}, headings_found

    # Build spans: from marker start to next marker start
    sections: Dict[str, str] = {}
    spans: Dict[str, Tuple[int, int]] = {}

    for idx, (key, s0) in enumerate(markers):
        s1 = markers[idx + 1][1] if idx + 1 < len(markers) else len(lin.text)
        # Do not include the heading line itself; clip to after its block end if possible
        # Find the block that starts at s0 and use its end
        heading_end = None
        for a, b_end, blk in lin.spans:
            if a == s0 and blk.kind in {"heading", "subheading"}:
                heading_end = b_end
                break
        content_start = heading_end if heading_end is not None else s0
        content = lin.text[content_start:s1].strip()

        # First one wins; later duplicates are appended with a warning
        if key in sections and content:
            diag.warn(
                "body.duplicate_section_heading",
                f"Duplicate section heading for {key}; appending content.",
                field="body",
                meta={"section": key},
            )
            sections[key] = (sections[key].rstrip() + "\n\n" + content).strip()
            # Expand span to include the appended content
            spans[key] = (spans[key][0], s1)
        else:
            sections[key] = content
            spans[key] = (content_start, s1)

    return sections, spans, headings_found


# -----------------------------------------------------------------------------
# Existing extractors (reuse your existing logic)
# -----------------------------------------------------------------------------


import re

# 1) "canceled range" marker: 1-4. (canceled)
_CANCELED_RANGE_RX = re.compile(
    r"(?P<start>\b\d{1,3})\s*[-–]\s*(?P<end>\d{1,3})\s*\.\s*"
    r"\(?\s*(?:cance(?:l|ll)ed|cancel(?:l|)ed)\s*\)?",
    re.IGNORECASE,
)

# 2) normal claim marker: 5. An edge inspection method...
# Require a reasonable token after the dot to avoid matching "0077." etc.
_CLAIM_MARKER_RX = re.compile(
    r"(?<!\d)"  # avoid mid-number
    r"(?P<num>\b\d{1,3})"  # claim number
    r"\s*\.\s*"
    r"(?=[A-Z(])",  # next token usually starts with capital or "("
)

# Standard claims anchor phrase (most reliable)
_CLAIMS_ANCHOR_RX = re.compile(
    r"\b(what\s+is\s+claimed\s+is|the\s+invention\s+claimed\s+is|i\s*/\s*we\s+claim)\b\s*:?",
    re.IGNORECASE,
)

# Optional: typical pre-claims phrase
_PRECLAIMS_HINT_RX = re.compile(
    r"\blimited\s+only\s+by\s+the\s+claims\b", re.IGNORECASE
)


def find_claims_start_offset(body_text: str) -> Optional[int]:
    if not body_text or len(body_text) < 2000:
        return None

    text = body_text

    # FIRST: Check for standard claims anchor phrase (most reliable)
    # Search from 30% onwards (claims usually in latter half)
    search_from = int(len(text) * 0.30)
    anchor_match = _CLAIMS_ANCHOR_RX.search(text, search_from)
    if anchor_match:
        return anchor_match.end()  # Start after the anchor phrase

    # FALLBACK: Search for numbered list pattern
    # Search window: bias toward end (claims usually late)
    start_search_at = int(len(text) * 0.40)
    hay = text[start_search_at:]

    # If we see the classic pre-claims hint, start searching shortly after it.
    m_hint = _PRECLAIMS_HINT_RX.search(hay)
    if m_hint:
        hay2 = hay[m_hint.end() :]
        base = start_search_at + m_hint.end()
    else:
        hay2 = hay
        base = start_search_at

    # Candidate starts = canceled ranges + normal claim markers
    candidates = []
    for m in _CANCELED_RANGE_RX.finditer(hay2):
        candidates.append(base + m.start("start"))
    for m in _CLAIM_MARKER_RX.finditer(hay2):
        candidates.append(base + m.start("num"))

    candidates = sorted(set(candidates))
    if not candidates:
        return None

    # Validate: does a "claims run" follow?
    # We require >=3 claim markers in the next window to accept.
    RUN_WINDOW = 2200
    MIN_MARKERS = 3

    for off in candidates:
        window = text[off : off + RUN_WINDOW]
        count = len(_CLAIM_MARKER_RX.findall(window))
        # If the first thing is a canceled range, we still expect subsequent numbered claims.
        if count >= MIN_MARKERS:
            return off

    return None


def _extract_claims_block(
    body_text: str, sections: Dict[str, str], diag: Diagnostics
) -> Tuple[str, str]:
    if "claims" in sections and sections["claims"].strip():
        return sections["claims"], "section"

    start = find_claims_start_offset(body_text)
    if start is not None:
        return body_text[start:].strip(), "anchor"

    diag.warn(
        "body.claims.block_not_found",
        "Could not identify claims block by section or anchor.",
        field="claims",
    )
    return "", "none"


# -----------------------------------------------------------------------------
# NEW entrypoint: parse from BodyResult
# -----------------------------------------------------------------------------


def parse_patent_body_from_body_result(
    *,
    body: Any,  # BodyResult
    diag: Diagnostics,
    policy: PatentBodyPolicy = PatentBodyPolicy(),
    expected_claim_count: int | None = None,
    expected_drawing_count: int | None = None,
) -> PatentBodyData:
    """
    Parse patent body using pre-segmented blocks (BodyResult).

    We assume blocks are already in reading order and already split into
    heading/subheading/paragraph kinds.
    """
    from doc_extractor.common import normalize_punctuation_spacing
    from doc_extractor.structured_logger import get_logger

    logger = get_logger(__name__)

    blocks = [b for b in _iter_body_blocks(body) if (b.text or "").strip()]
    logger.info("linearizing blocks", block_count=len(blocks))
    lin = _linearize_blocks(blocks)
    body_text = normalize_punctuation_spacing(lin.text)

    # Sections from headings (primary)
    sections, spans, headings_found = _sections_from_blocks(lin, diag)
    logger.info(
        "sections extracted from headings",
        heading_count=len(headings_found),
        section_count=len(sections),
        headings=headings_found,
    )
    if not sections:
        diag.warn(
            "body.no_section_headings_detected",
            "No section headings detected from heading blocks; proceeding with fallback heuristics.",
            field="body",
        )

    # Drawings: prefer drawings section
    drawings_text = sections.get("brief_description_of_drawings", "")
    drawings_items = extract_drawing_descriptions(drawings_text)
    drawings_method = "section" if drawings_items else "none"

    if not drawings_items:
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

    # Claims: prefer explicit claims section; else anchor
    claims_block, claims_method = _extract_claims_block(body_text, sections, diag)
    chunks = _parse_claims_from_block(claims_block, expected_count=expected_claim_count)
    claims = claims_from_chunks(chunks)
    # if expected_claim_count is not None:
    # claims = claims[:expected_claim_count]  # allow some overrun for warnings
    validate_claims(claims, diag)
    claims_count = len(claims)

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

    # Figures referenced: constrain to drawings items if present, else drawings section only
    if drawings_items:
        figure_ids = sorted(
            {
                f"{row['figure_number']}{row.get('figure_suffix') or ''}".upper()
                for row in drawings_items
                if row.get("figure_number")
            }
        )
        fig_source = f"drawings_items:{drawings_method}"
    else:
        figure_ids = _extract_figure_ids(drawings_text)
        fig_source = "drawings_section_text"

    fig_count = len(figure_ids)

    if expected_drawing_count is not None:
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

    claims = ClaimsData(count=claims_count, items=tuple(claims), method=claims_method)
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
            "figure_id_source": fig_source,
            "linearized_blocks": len(lin.spans),
        },
    )


def parse_patent_body_from_body_result_fallible(
    *,
    body: Any,
    policy: PatentBodyPolicy = PatentBodyPolicy(),
    expected_claim_count: int | None = None,
    expected_drawing_count: int | None = None,
) -> PatentBodyResult:
    diag = Diagnostics()
    try:
        data = parse_patent_body_from_body_result(
            body=body,
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
            status=PatentBodyStatus.FAILED, data=None, diagnostics=diag, meta={}
        )

    if any(diag.errors()):
        status = (
            PatentBodyStatus.FAILED
            if policy.fail_on_error
            else PatentBodyStatus.PARTIAL
        )
    elif any(diag.warnings()):
        status = PatentBodyStatus.PARTIAL
    else:
        status = PatentBodyStatus.OK

    return PatentBodyResult(status=status, data=data, diagnostics=diag, meta={})
