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

    if policy.warnings_are_errors and diag.warnings:
        for w in diag.warnings:
            diag.errors.append(w)
        diag.warnings.clear()

    if diag.errors:
        return DrawingSheetsStatus.FAILED

    if policy.require_at_least_one_region and len(data.regions) == 0:
        diag.error(
            "drawing_sheets.none_found",
            "No drawing regions were detected.",
            field="drawing_sheets",
        )
        return DrawingSheetsStatus.FAILED

    # Optional: enforce expected sheet count (pages scanned)
    if policy.expected_sheet_count is not None:
        found = len(data.pages)
        exp = policy.expected_sheet_count
        if found != exp:
            msg = f"Drawing sheet page range has {found} pages, expected {exp}."
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

    return DrawingSheetsStatus.PARTIAL if diag.warnings else DrawingSheetsStatus.OK


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
    page_indices: Sequence[int],  # explicit page indices (0-based)
    diag: Diagnostics,
    *,
    policy: DrawingSheetsPolicy = DrawingSheetsPolicy(),
) -> DrawingSheetsResult:
    """
    Fallible: never raises for expected issues. On catastrophic exceptions returns FAILED with diagnostics.
    Parsing returns only regions (bbox + metadata). Export is handled elsewhere.
    """
    try:
        # 0) Check all the pages passed are valid drawing sheets

        # Heuristic validation (non-authoritative)
        heuristic_hits = []
        reader = PdfReader(pdf_path)
        for i in page_indices:
            text = reader.pages[i].extract_text() or ""
            if _SHEET_OF_RE.search(text):
                heuristic_hits.append(i)
        if heuristic_hits != page_indices:
            diag.error(
                "drawing_sheets.heuristic_mismatch",
                "Heuristic check for 'Sheet X of Y' patterns did not match expected drawing sheet pages.",
            )
            return DrawingSheetsResult(
                status=DrawingSheetsStatus.FAILED,
                data=None,
                diagnostics=diag,
                meta={"pdf_path": pdf_path},
            )

        # 1) Open PDF and locate drawings per page
        parses: list[SheetParse] = []

        for p in page_indices:
            try:
                sheet = _segment_drawings_on_page(  # your per-page function
                    pdf_path,
                    p,
                    diag,
                    # pass through segmentation parameters here
                )
                parses.append(sheet)
            except Exception as e:
                # per-page failures are usually warnings => PARTIAL
                diag.warn(
                    "drawing_sheets.page_failed",
                    f"Failed to parse drawing sheet page {p}: {e}",
                    field="drawing_sheets",
                    meta={"page": p},
                )

        data = aggregate_sheet_parses(
            pdf_path, parses, diag, expected_pages=page_indices
        )

    except Exception as e:
        diag.error(
            "drawing_sheets.exception",
            f"Unhandled exception during drawing sheets parsing: {e}",
            field="drawing_sheets",
            meta={"pdf_path": pdf_path},
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
