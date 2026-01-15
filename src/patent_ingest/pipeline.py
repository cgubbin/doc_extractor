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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pypdf import PdfReader

# --- Imports from your existing modules ---
# Adjust these import paths if your package structure differs.
from patent_ingest.parse_front_page import parse_front_matter, extract_page_text
from patent_ingest.parse_body import parse_patent_body
from patent_ingest.drawing_sheets import process_drawing_sheets
from patent_ingest.utils import infer_drawings_start_index
from patent_ingest.assembler import assemble_parsed_patent


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


def _safe_mkdir(p: Optional[str | Path]) -> Optional[Path]:
    if p is None:
        return None
    out = Path(p)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _aggregate_qa(*qa_blocks: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    warnings: List[str] = []
    info: Dict[str, Any] = {}
    for qa in qa_blocks:
        if not qa:
            continue
        warnings.extend(list(qa.get("warnings") or []))
        # merge info shallowly; later keys win (fine for orchestration)
        info.update(dict(qa.get("info") or {}))
    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    return {"warnings": deduped, "info": info}


def _build_front_matter_pages_text(
    reader: PdfReader,
    *,
    pages_to_scan: int,
) -> List[str]:
    # n = min(pages_to_scan, len(reader.pages))
    n = min(pages_to_scan, reader.page_count)
    pages_text: List[str] = []
    for i in range(n):
        # Keep parity with your existing code: front-page flag only for page 0
        pages_text.append(extract_page_text(reader, i, is_front_page=(i == 0)) or "")
    return pages_text


def ingest_patent_pdf(
    pdf_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    config: OrchestratorConfig = OrchestratorConfig(),
    front_matter_pages_to_scan: Optional[int] = None,  # still allowed as override/debug
) -> Dict[str, Any]:
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
    import pymupdf  # noqa: F401

    pdf_path = str(pdf_path)
    out_root = _safe_mkdir(output_dir)

    reader = PdfReader(pdf_path)
    doc = pymupdf.open(pdf_path)
    pdf_num_pages = len(reader.pages)

    # -----------------------
    # Step 1: minimal parse (page 0 only) to get reported drawing sheet count (and claim count)
    # -----------------------
    pages_text_min = _build_front_matter_pages_text(
        doc, pages_to_scan=min(1, pdf_num_pages)
    )
    front_min = parse_front_matter(pages_text_min, max_pages=len(pages_text_min))

    reported_counts = front_min.get("reported_counts") or {}
    expected_sheet_count = reported_counts.get("reported_drawing_sheet_count")
    expected_claim_count = reported_counts.get("reported_claim_count")

    print("=== Initial Front-matter parsing complete ===")
    print(front_min)
    raise NotImplementedError("Update imports and helper calls as needed.")

    # -----------------------
    # Step 1b: determine front-matter boundary (drawings_start_index)
    # -----------------------
    drawings_start_index = None
    inference_used = False

    if (
        front_matter_pages_to_scan is None
        and isinstance(expected_sheet_count, int)
        and expected_sheet_count > 0
    ):
        # Prefer explicit "Sheet i of n" detection if available in your helper;
        # else fallback to score-based inference.
        drawings_start_index = infer_drawings_start_index(reader, expected_sheet_count)
        inference_used = True

    if front_matter_pages_to_scan is not None:
        pages_to_scan = min(front_matter_pages_to_scan, pdf_num_pages)
        inference_used = False
    else:
        if drawings_start_index is None:
            # Conservative fallback: parse first 3 pages as front matter, but emit warning.
            pages_to_scan = min(3, pdf_num_pages)
        else:
            pages_to_scan = min(drawings_start_index, pdf_num_pages)

    # -----------------------
    # Step 1c: full front matter parse up to boundary
    # -----------------------
    pages_text = _build_front_matter_pages_text(reader, pages_to_scan=pages_to_scan)
    front = parse_front_matter(pages_text, max_pages=len(pages_text))

    front.setdefault("qa", {}).setdefault("info", {})
    front["qa"]["info"].update(
        {
            "front_matter_pages_inferred": inference_used,
            "front_matter_pages_scanned": len(pages_text),
            "drawings_start_index_inferred": drawings_start_index,
        }
    )

    # Use the “full” front parse if it has better values
    reported_counts_full = front.get("reported_counts") or {}
    expected_sheet_count = reported_counts_full.get(
        "reported_drawing_sheet_count", expected_sheet_count
    )
    expected_claim_count = reported_counts_full.get(
        "reported_claim_count", expected_claim_count
    )

    # -----------------------
    # Step 2: drawing sheets
    # -----------------------
    drawings_out_dir = None
    if out_root is not None:
        drawings_out_dir = out_root / "drawings"
        drawings_out_dir.mkdir(parents=True, exist_ok=True)

    drawings = process_drawing_sheets(
        pdf_path,
        drawing_sheets_expected=expected_sheet_count,
        first_drawing_sheet_index=drawings_start_index,
        output_dir=str(drawings_out_dir) if drawings_out_dir else None,
        export_pdf=config.export_pdf,
        max_pages_scan=10,
        detect_figures=True,
        export_figures_png=config.export_png,
        export_png=config.export_png,
    )

    drawing_sheets = (
        drawings.get("drawing_sheets") if isinstance(drawings, dict) else drawings
    )
    sheet_count = (drawing_sheets or {}).get("sheet_count")
    drawing_count_total = (drawing_sheets or {}).get(
        "drawing_count_total"
    )  # may be None if not segmented

    # Determine body start index deterministically:
    # if we know drawings start and count, body starts right after drawings.
    body_start_index = None
    if (
        isinstance(drawings_start_index, int)
        and isinstance(sheet_count, int)
        and sheet_count > 0
    ):
        body_start_index = drawings_start_index + sheet_count

    # -----------------------
    # Step 3: patent body (remaining pages)
    # -----------------------
    body_out_dir = None
    if out_root is not None:
        body_out_dir = out_root / "body"
        body_out_dir.mkdir(parents=True, exist_ok=True)

    patent_body = parse_patent_body(
        pdf_path=pdf_path,
        start_page_index=body_start_index,  # may be None; module must handle gracefully + QA
        output_dir=str(body_out_dir) if body_out_dir else None,
        expected_claim_count=expected_claim_count,
        expected_drawing_count=drawing_count_total,
        expected_sheet_count=expected_sheet_count,
    )

    # -----------------------
    # Aggregate QA
    # -----------------------
    qa = _aggregate_qa(
        front.get("qa"),
        drawings.get("qa") if isinstance(drawings, dict) else None,
        patent_body.get("qa"),
    )
    qa.setdefault("info", {})
    qa["info"].update(
        {
            "pdf_path": pdf_path,
            "pdf_num_pages": pdf_num_pages,
            "drawings_start_index": drawings_start_index,
            "body_start_index": body_start_index,
            "expected_claim_count": expected_claim_count,
            "expected_sheet_count": expected_sheet_count,
            "expected_drawing_count": drawing_count_total,
        }
    )

    assembled = assemble_parsed_patent(
        pdf_path=pdf_path,
        front_matter=front,
        drawing_result=drawings,
        body_result=patent_body,
    )

    print("=== Ingestion complete ===")
    print("Document consistency:")
    print(assembled["consistency"])
    print("Document qa:")
    print(assembled["qa"])

    return assembled
