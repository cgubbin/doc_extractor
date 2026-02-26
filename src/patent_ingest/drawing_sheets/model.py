from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence, Tuple, Dict

from patent_ingest.diagnostics import Diagnostics
from patent_ingest.drawing_sheets.policy import DrawingSheetsPolicy
from patent_ingest.drawing_sheets.segment import (
    _segment_drawings_on_page,
    PDFPageRef,
    SheetParse,
    BBox,
)


@dataclass(frozen=True)
class DrawingRegion:
    page: PDFPageRef
    bbox: BBox
    confidence: float = 0.5
    source: str = "image-segmentation"  # or "vector" / "heuristic"
    meta: dict[str, Any] = field(default_factory=dict)


class DrawingSheetsStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class DrawingSheetsData:
    pdf_path: str
    sheets: Tuple[SheetParse, ...]
    meta: Dict[str, Any] = field(default_factory=dict)
    num_sheets: int = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "num_sheets", len(self.sheets))

    @property
    def regions(self) -> Tuple[DrawingRegion, ...]:
        # convenient flatten (computed view)
        out = []
        for s in self.sheets:
            out.extend(s.regions)
        return tuple(out)

    def regions_by_page(self) -> Dict[int, Tuple[DrawingRegion, ...]]:
        out: Dict[int, list[DrawingRegion]] = {}
        for s in self.sheets:
            out.setdefault(s.page.page_index, []).extend(list(s.regions))
        return {k: tuple(v) for k, v in out.items()}


@dataclass(frozen=True)
class DrawingSheetsResult:
    status: DrawingSheetsStatus
    data: Optional[DrawingSheetsData]  # None only on catastrophic failure
    diagnostics: Diagnostics
    meta: dict[str, Any] = field(default_factory=dict)


def determine_drawing_sheets_status(
    data: Optional[DrawingSheetsData],
    diag: Diagnostics,
    policy: DrawingSheetsPolicy,
) -> DrawingSheetsStatus:
    if data is None:
        return DrawingSheetsStatus.FAILED

    # warnings->errors (if you support this mechanic)
    if policy.warnings_are_errors:
        for w in list(diag.warnings()):
            diag.error(w.code, w.message, field="drawing_sheets", **(w.meta or {}))

    if any(diag.errors()):
        return DrawingSheetsStatus.FAILED

    if policy.require_at_least_one_region and len(data.regions) == 0:
        diag.error(
            "drawing_sheets.none_found",
            "No drawing regions were detected.",
            field="drawing_sheets",
        )
        return DrawingSheetsStatus.FAILED

    if policy.expected_sheet_count is not None:
        found = len(data.sheets)
        exp = policy.expected_sheet_count
        if found != exp:
            msg = f"Parsed {found} drawing sheets, expected {exp}."
            if policy.strict_expected_sheet_count:
                diag.error(
                    "drawing_sheets.sheet_count_mismatch",
                    msg,
                    field="drawing_sheets",
                    expected=exp,
                    found=found,
                )
                return DrawingSheetsStatus.FAILED
            diag.warn(
                "drawing_sheets.sheet_count_mismatch",
                msg,
                field="drawing_sheets",
                expected=exp,
                found=found,
            )
            return DrawingSheetsStatus.PARTIAL

    return (
        DrawingSheetsStatus.PARTIAL if any(diag.warnings()) else DrawingSheetsStatus.OK
    )


from pypdf import PdfReader
import re

_SHEET_OF_RE = re.compile(r"\bSheet\s+([0-9A-Za-z]+)\s+of\s+([0-9]+)\b", re.IGNORECASE)


def aggregate_sheet_parses(
    pdf_path: str,
    parses: Sequence[SheetParse],
    diag: Diagnostics,
    *,
    expected_pages: Optional[Sequence[int]] = None,
) -> DrawingSheetsData:
    # 1) sort deterministically
    parses_sorted = sorted(parses, key=lambda s: s.page.page_index)

    # 2) detect duplicates / missing pages
    seen = set()
    unique: list[SheetParse] = []
    for s in parses_sorted:
        p = s.page.page_index
        if p in seen:
            diag.warn(
                "drawing_sheets.duplicate_page",
                f"Duplicate SheetParse for page {p}; keeping first.",
                field="drawing_sheets",
                meta={"page": p},
            )
            continue
        seen.add(p)
        unique.append(s)

    if expected_pages is not None:
        exp = set(expected_pages)
        got = set(seen)
        missing = sorted(exp - got)
        extra = sorted(got - exp)
        if missing:
            diag.warn(
                "drawing_sheets.pages_missing",
                f"Some expected drawing-sheet pages were not parsed: {missing}",
                field="drawing_sheets",
                meta={"missing": missing},
            )
        if extra:
            diag.warn(
                "drawing_sheets.pages_unexpected",
                f"Some parsed pages were not in the expected set: {extra}",
                field="drawing_sheets",
                meta={"extra": extra},
            )

    # 3) compute useful meta
    total_regions = sum(len(s.regions) for s in unique)
    meta = {
        "pages_parsed": [s.page.page_index for s in unique],
        "sheet_count": len(unique),
        "region_count": total_regions,
        "dpi_set": sorted({s.render.dpi for s in unique}),
    }

    return DrawingSheetsData(pdf_path=pdf_path, sheets=tuple(unique), meta=meta)


def parse_drawing_sheets(
    pdf_path: str,
    page_indices: Sequence[int],
    diag: Diagnostics,
    *,
    policy: DrawingSheetsPolicy = DrawingSheetsPolicy(),
) -> DrawingSheetsResult:
    try:
        # 0) Optional heuristic validation (non-authoritative)
        if policy.validate_sheet_of_marker and page_indices:
            reader = PdfReader(pdf_path)
            hits = []
            for i in page_indices:
                try:
                    text = reader.pages[i].extract_text() or ""
                except Exception:
                    text = ""
                if _SHEET_OF_RE.search(text):
                    hits.append(i)

            hit_rate = len(hits) / max(1, len(page_indices))
            if hit_rate < policy.min_sheet_of_hit_rate:
                msg = (
                    f"'Sheet X of Y' marker hit rate {hit_rate:.2f} "
                    f"({len(hits)}/{len(page_indices)}) on supposed drawing pages."
                )
                if policy.strict_sheet_of_marker:
                    diag.error(
                        "drawing_sheets.sheet_of_low_hit_rate",
                        msg,
                        field="drawing_sheets",
                        hit_rate=hit_rate,
                    )
                    return DrawingSheetsResult(
                        status=DrawingSheetsStatus.FAILED,
                        data=None,
                        diagnostics=diag,
                        meta={"pdf_path": pdf_path},
                    )
                diag.warn(
                    "drawing_sheets.sheet_of_low_hit_rate",
                    msg,
                    field="drawing_sheets",
                    hit_rate=hit_rate,
                )

        parses: list[SheetParse] = []
        for p in page_indices:
            try:
                sheet = _segment_drawings_on_page(pdf_path, p, diag)
                parses.append(sheet)
            except Exception as e:
                diag.warn(
                    "drawing_sheets.page_failed",
                    f"Failed to parse drawing sheet page {p}: {e}",
                    field="drawing_sheets",
                    page=p,
                )

        data = aggregate_sheet_parses(
            pdf_path, parses, diag, expected_pages=page_indices
        )

    except Exception as e:
        diag.error(
            "drawing_sheets.exception",
            f"Unhandled exception during drawing sheets parsing: {type(e).__name__}: {e}",
            field="drawing_sheets",
            pdf_path=pdf_path,
        )
        return DrawingSheetsResult(
            status=DrawingSheetsStatus.FAILED,
            data=None,
            diagnostics=diag,
            meta={"pdf_path": pdf_path},
        )

    status = determine_drawing_sheets_status(data, diag, policy)
    return DrawingSheetsResult(
        status=status, data=data, diagnostics=diag, meta={"pdf_path": pdf_path}
    )
