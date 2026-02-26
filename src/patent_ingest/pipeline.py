"""
patent_ingest.pipeline

Orchestration layer that runs:
  1) Front-matter parsing (multi-page)
  2) Drawing-sheets processing (using front-matter metadata)

This module is intentionally lightweight: it wires together existing modules and
standardizes return structure and QA aggregation.

Expected existing functions (from your codebase):
  - patent_ingest.parse_front_page.parse_front_matter(pages_text: list[str], max_pages: int) -> dict
  - patent_ingest.parse_front_page.extract_page_text(reader, page_index: int, is_front_page: bool = False) -> str
    OR equivalent helper you already use to build pages_text.
  - patent_ingest.drawing_sheets.process_drawing_sheets(pdf_path: str, front_matter: dict, ...) -> dict
  - Optional: canonical helpers (canonical_front_page, canonical_drawing_sheets)

If your parse_front_matter signature or helper names differ, update the imports
at the top accordingly; the orchestration logic should remain stable.
"""

from __future__ import annotations

from enum import Enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional
import pymupdf


# --- Imports from your existing modules ---
# Adjust these import paths if your package structure differs.
from patent_ingest.inid_parse import (
    parse_inids,
    ParsePolicy,
    ParsedFrontMatterV1,
    MissingRequiredINIDs,
)
from patent_ingest.body.parse import (
    parse_patent_body_from_body_result_fallible,
    PatentBodyData,
)
from patent_ingest.drawing_sheets.model import parse_drawing_sheets, DrawingSheetsData
from patent_ingest.model.analysis import analyze_document
from patent_ingest.diagnostics import Diagnostics
from patent_ingest.structured_logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class OrchestratorConfig:
    """
    Configuration for the end-to-end ingestion pipeline.

    front_matter_pages_to_scan:
      Number of pages (starting at page 0) to build into pages_text for front-matter parsing.
      This should be >= 2 for many patents where references continue onto page 2.
    """

    export_pdf: bool = True
    export_png: bool = True
    segment_drawings: bool = True


class IngestStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class IngestionData:
    front_matter: ParsedFrontMatterV1
    drawing_sheets: Optional[DrawingSheetsData] = None
    body: Optional[PatentBodyData] = None


@dataclass(frozen=True)
class IngestionResult:
    status: IngestStatus
    diagnostics: Diagnostics
    data: Optional[IngestionData] = None
    meta: Dict[str, Any] = field(
        default_factory=dict
    )  # optional: pages_used, version, etc.


@dataclass(frozen=True)
class IngestPolicy:
    required_fields: tuple[str, ...] = ("patent_id",)
    fail_on_error: bool = False  # batch-friendly default
    warn_on_missing_optional: bool = True


def determine_status(
    data: Optional[IngestionData], diag: Diagnostics, policy: IngestPolicy
) -> IngestStatus:
    if data is None:
        return IngestStatus.FAILED
    if diag.errors:
        return IngestStatus.FAILED if policy.fail_on_error else IngestStatus.PARTIAL

    # If required fields missing, treat as failure/partial depending on policy
    for f in policy.required_fields:
        v = getattr(data, f, None)
        missing = (v is None) or (isinstance(v, list) and not v)
        if missing:
            return IngestStatus.FAILED if policy.fail_on_error else IngestStatus.PARTIAL

    return IngestStatus.OK


def _safe_mkdir(p: Optional[str | Path]) -> Optional[Path]:
    if p is None:
        return None
    out = Path(p)
    out.mkdir(parents=True, exist_ok=True)
    return out


def ingest_patent_pdf(
    path: str | Path,
    *,
    output_dir: str | Path | None = None,
    config: OrchestratorConfig = OrchestratorConfig(),
    policy: IngestPolicy = IngestPolicy(),
) -> IngestionResult:
    """
    End-to-end pipeline:
      1) Front matter (multi-page)
      2) Drawing sheets (N pages after front matter; inferred boundary)
      3) Patent body (remainder after drawings): sections + claims extraction + QA cross-checks

    Returns a single structured dict:
      {
        pdf_path,
        front_matter,
        drawing_sheets,
        patent_body,
        qa
      }
    """
    diag = Diagnostics()

    logger.info("ingestion_started", pdf_path=str(path))

    try:
        doc = pymupdf.open(path)
        logger.info("pdf_loaded", pdf_path=str(path), page_count=len(doc))
    except Exception as e:
        diag.error(
            "pdf.read_failure",
            f"Failed to read PDF at {path}: {e}",
            exception=e,
        )
        logger.error("pdf_load_failed", pdf_path=str(path), error=str(e))
        return IngestionResult(
            status=IngestStatus.FAILED, data=None, diagnostics=diag, meta={"path": path}
        )

    try:
        read = analyze_document(doc)
        logger.info("pdf_read", pdf_path=str(path), page_count=len(doc))
    except Exception as e:
        diag.error(
            "pdf.read_failure",
            f"Failed to analyse PDF at {path}: {e}",
            exception=e,
        )
        logger.error("pdf_load_failed", pdf_path=str(path), error=str(e))
        return IngestionResult(
            status=IngestStatus.FAILED, data=None, diagnostics=diag, meta={"path": path}
        )

    # TODO; Use the ingestion policy...

    logger.info("front_matter_parsing_started")

    try:
        front_matter = parse_inids(read.inid, policy=ParsePolicy())
        diag.merge(front_matter.diagnostics)

        logger.info(
            "front_matter_parsing_completed",
            pages_scanned=front_matter.pages,
            errors=front_matter.diagnostics.num_errors(),
            warnings=front_matter.diagnostics.num_warnings(),
        )
    except MissingRequiredINIDs as e:
        # known/expected quality failure
        diag.merge(e.diagnostics)
        diag.error("front_matter.missing_required", str(e), field="front_matter")
        logger.info(
            "front_matter_parsing_incomplete", missing=getattr(e, "missing", None)
        )
        return IngestionResult(
            status=IngestStatus.FAILED, data=None, diagnostics=diag, meta={"path": path}
        )
    except Exception as e:
        diag.error(
            "parse.exception",
            f"Unhandled exception during parsing: {type(e).__name__}: {e}",
            field="parse",
            exc_type=type(e).__name__,
        )
        logger.error("front_matter_parsing_failed", error=str(e), exc_info=True)
        return IngestionResult(
            status=IngestStatus.FAILED, data=None, diagnostics=diag, meta={"path": path}
        )

    # drawing pages: trust detection, treat reported count as a check
    num_drawing_pages = read.drawings.count
    reported = getattr(front_matter.technical, "drawing_sheets_count", None)
    if reported is not None:
        if reported != num_drawing_pages:
            diag.warn(
                "drawing_sheets.count_mismatch",
                f"Reported drawing sheets count ({reported}) does not match detected drawing pages ({num_drawing_pages}).",
                reported=reported,
                detected=num_drawing_pages,
            )
    else:
        diag.warn(
            "drawing_sheets.no_reported_count",
            "No reported drawing sheet count found; cannot verify OCR count.",
        )

    front_span = (max(front_matter.pages) + 1) if front_matter.pages else 0
    drawing_indices = read.drawings.page_indices or []

    drawing_start = min(drawing_indices) if drawing_indices else front_span
    drawing_end = max(drawing_indices) if drawing_indices else (drawing_start - 1)

    logger.info(
        "drawing_sheets_parsing_started",
        detected_pages=len(drawing_indices),
        reported_pages=getattr(front_matter.technical, "drawing_sheets_count", None),
        page_range=f"{drawing_start}-{drawing_end}" if drawing_indices else None,
    )

    drawing_sheets_data = None
    try:
        # prefer no shared diag passed in
        result = parse_drawing_sheets(path, drawing_indices, diag=diag)
        diag.merge(result.diagnostics)
        drawing_sheets_data = result.data

        logger.info(
            "drawing_sheets_parsing_completed",
            sheets_parsed=getattr(drawing_sheets_data, "num_sheets", None),
            errors=result.diagnostics.num_errors(),
            warnings=result.diagnostics.num_warnings(),
        )
    except Exception as e:
        diag.error(
            "drawing.parse.exception", f"{type(e).__name__}: {e}", field="drawing"
        )
        logger.error("drawing_sheets_parsing_failed", error=str(e), exc_info=True)
        # continue; drawings are optional for body parsing

    logger.info(
        "body_parsing_started", pages=len(read.body.pages), blocks=len(read.body.blocks)
    )

    try:
        result = parse_patent_body_from_body_result_fallible(body=read.body)
        diag.merge(result.diagnostics)
        patent_body_data = result.data
        logger.info(
            "body_parsing_completed",
            errors=result.diagnostics.num_errors(),
            warnings=result.diagnostics.num_warnings(),
        )
    except Exception as e:
        diag.error(
            "parse.exception", f"Unhandled exception during parsing: {e}", field="parse"
        )
        logger.error("body_parsing_failed", error=str(e), exc_info=True)
        return IngestionResult(
            status=IngestStatus.FAILED, data=None, diagnostics=diag, meta={"path": path}
        )

    ingestion_data = IngestionData(
        front_matter=front_matter,
        drawing_sheets=drawing_sheets_data,
        body=patent_body_data,
    )

    meta = {
        "path": path,
        "front_matter_pages_scanned": len(front_matter.pages),
    }
    if drawing_sheets_data is not None:
        meta["drawing_sheets_pages_scanned"] = drawing_sheets_data.num_sheets

    result = IngestionResult(
        status=determine_status(
            data=ingestion_data,
            diag=diag,
            policy=policy,
        ),
        data=ingestion_data,
        diagnostics=diag,
        meta=meta,
    )

    for each in diag.errors():
        print(f"ERROR: {each}")

    logger.info(
        "ingestion_completed",
        pdf_path=str(path),
        status=result.status.value,
        total_errors=diag.num_errors(),
        total_warnings=diag.num_warnings(),
        total_info=diag.num_info(),
    )

    return result
