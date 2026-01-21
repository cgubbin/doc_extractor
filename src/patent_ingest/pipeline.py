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


# --- Imports from your existing modules ---
# Adjust these import paths if your package structure differs.
from patent_ingest.front_matter.model import (
    FrontMatterData,
    parse_front_matter,
)
from patent_ingest.body.parse import parse_patent_body_fallible, PatentBodyData
from patent_ingest.drawing_sheets.model import parse_drawing_sheets, DrawingSheetsData
from patent_ingest.model.document import read_pdf_to_multipage
from patent_ingest.diagnostics import Diagnostics
from patent_ingest.logging import get_logger

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
    front_matter: FrontMatterData
    drawing_sheets: DrawingSheetsData
    body: PatentBodyData


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
        doc = read_pdf_to_multipage(path)
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

    logger.info("front_matter_parsing_started")

    try:
        result = parse_front_matter(doc)  # returns FrontMatterResult(data, diagnostics)
        diag.merge(result.diagnostics)
        front_matter_data = result.data
        logger.info(
            "front_matter_parsing_completed",
            pages_scanned=front_matter_data.num_sheets,
            errors=len(result.diagnostics.errors),
            warnings=len(result.diagnostics.warnings),
        )
    except Exception as e:
        diag.error(
            "parse.exception", f"Unhandled exception during parsing: {e}", field="parse"
        )
        logger.error("front_matter_parsing_failed", error=str(e))
        return IngestionResult(
            status=IngestStatus.FAILED, data=None, diagnostics=diag, meta={"path": path}
        )

    # partition the pdf:
    num_front_pages = front_matter_data.num_sheets
    num_drawing_pages = (
        front_matter_data.reported_counts.value.reported_drawing_sheet_count
    )
    total_pages = len(doc)
    remaining_doc = doc.subset(
        pages=range(num_front_pages + num_drawing_pages, total_pages)
    )

    logger.info(
        "drawing_sheets_parsing_started",
        expected_pages=num_drawing_pages,
        page_range=f"{num_front_pages}-{num_front_pages + num_drawing_pages - 1}",
    )

    try:
        pages = [
            ii for ii in range(num_front_pages, num_front_pages + num_drawing_pages)
        ]
        result = parse_drawing_sheets(path, pages, diag)  # returns DrawingSheetsResult
        diag.merge(result.diagnostics)
        drawing_sheets_data = result.data
        logger.info(
            "drawing_sheets_parsing_completed",
            sheets_parsed=drawing_sheets_data.num_sheets,
            errors=len(result.diagnostics.errors),
            warnings=len(result.diagnostics.warnings),
        )
    except Exception as e:
        diag.error(
            "parse.exception", f"Unhandled exception during parsing: {e}", field="parse"
        )
        logger.error("drawing_sheets_parsing_failed", error=str(e))
        return IngestionResult(
            status=IngestStatus.FAILED, data=None, diagnostics=diag, meta={"path": path}
        )

    logger.info(
        "body_parsing_started",
        remaining_pages=len(remaining_doc),
    )

    try:
        result = parse_patent_body_fallible(doc=remaining_doc)
        diag.merge(result.diagnostics)
        patent_body_data = result.data
        logger.info(
            "body_parsing_completed",
            errors=len(result.diagnostics.errors),
            warnings=len(result.diagnostics.warnings),
        )
    except Exception as e:
        diag.error(
            "parse.exception", f"Unhandled exception during parsing: {e}", field="parse"
        )
        logger.error("body_parsing_failed", error=str(e))
        return IngestionResult(
            status=IngestStatus.FAILED, data=None, diagnostics=diag, meta={"path": path}
        )

    result = IngestionResult(
        status=determine_status(
            data=IngestionData(
                front_matter=front_matter_data,
                drawing_sheets=drawing_sheets_data,
                body=patent_body_data,
            ),
            diag=diag,
            policy=policy,
        ),
        data=IngestionData(
            front_matter=front_matter_data,
            drawing_sheets=drawing_sheets_data,
            body=patent_body_data,
        ),
        diagnostics=diag,
        meta={
            "path": path,
            "front_matter_pages_scanned": front_matter_data.num_sheets,
            "drawing_sheets_pages_scanned": drawing_sheets_data.num_sheets,
        },
    )

    logger.info(
        "ingestion_completed",
        pdf_path=str(path),
        status=result.status.value,
        total_errors=len(diag.errors),
        total_warnings=len(diag.warnings),
        total_info=len(diag.info),
    )

    return result
