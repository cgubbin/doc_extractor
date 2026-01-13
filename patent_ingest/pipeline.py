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
from patent_ingest.drawing_sheets import process_drawing_sheets
from patent_ingest.utils import infer_drawings_start_index


@dataclass(frozen=True)
class OrchestratorConfig:
    """
    Configuration for the end-to-end ingestion pipeline.

    front_matter_pages_to_scan:
      Number of pages (starting at page 0) to build into pages_text for front-matter parsing.
      This should be >= 2 for many patents where references continue onto page 2.
    """

    export_pdf: bool = True
    export_png: bool = False
    segment_drawings: bool = False


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
    n = min(pages_to_scan, len(reader.pages))
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
    # Optional override: if set, skip inference and just scan this many pages as front matter
    front_matter_pages_to_scan: Optional[int] = None,
) -> Dict[str, Any]:
    pdf_path = str(pdf_path)
    out_root = _safe_mkdir(output_dir)

    reader = PdfReader(pdf_path)
    pdf_num_pages = len(reader.pages)

    # --- Phase 1: minimal front parse on page 0 only to get reported counts ---
    pages_text_min = _build_front_matter_pages_text(reader, pages_to_scan=min(1, pdf_num_pages))
    front_min = parse_front_matter(pages_text_min, max_pages=len(pages_text_min))

    reported = front_min.get("reported_counts") or {}
    expected_sheets = reported.get("reported_drawing_sheet_count")

    # --- Infer drawings start index unless user overrides front matter scanning ---
    drawings_start_index = None
    if (
        front_matter_pages_to_scan is None
        and isinstance(expected_sheets, int)
        and expected_sheets > 0
    ):
        drawings_start_index = infer_drawings_start_index(reader, expected_sheets)

    # Determine how many pages are front matter
    if front_matter_pages_to_scan is not None:
        pages_to_scan = min(front_matter_pages_to_scan, pdf_num_pages)
        inference_used = False
    else:
        # If inference fails, fall back to conservative baseline:
        # front page + up to 2 pages of metadata/references, but do NOT exceed document
        if drawings_start_index is None:
            pages_to_scan = min(3, pdf_num_pages)
            inference_used = True
        else:
            pages_to_scan = min(drawings_start_index, pdf_num_pages)
            inference_used = True

    pages_text = _build_front_matter_pages_text(reader, pages_to_scan=pages_to_scan)

    # --- Phase 2: full front matter parse (now that we know the boundary) ---
    front = parse_front_matter(pages_text, max_pages=len(pages_text))

    # Record inference diagnostics (so tests can ignore / you can debug)
    front.setdefault("qa", {}).setdefault("info", {})
    front["qa"]["info"]["front_matter_pages_inferred"] = inference_used
    front["qa"]["info"]["front_matter_pages_scanned"] = len(pages_text)
    front["qa"]["info"]["drawings_start_index_inferred"] = drawings_start_index
    front["qa"]["info"]["reported_drawing_sheet_count_min_parse"] = expected_sheets

    # --- Drawing sheets ---
    drawings_out_dir = None
    if out_root is not None:
        drawings_out_dir = out_root / "drawings"
        drawings_out_dir.mkdir(parents=True, exist_ok=True)

    drawings = process_drawing_sheets(
        pdf_path,
        front_matter=front,
        output_dir=str(drawings_out_dir) if drawings_out_dir else None,
        export_pdf=config.export_pdf,
        export_png=config.export_png,
        segment_drawings=config.segment_drawings,
        max_pages_scan=10,
        drawings_start_index=drawings_start_index,  # <-- add this param in drawing_sheets API
    )

    qa = _aggregate_qa(front.get("qa"), drawings.get("qa"))
    qa["info"].update(
        {
            "pdf_path": pdf_path,
            "pdf_num_pages": pdf_num_pages,
            "front_matter_pages_scanned": len(pages_text),
            "output_dir": str(out_root) if out_root else None,
            "drawings_start_index": drawings_start_index,
        }
    )

    return {
        "pdf_path": pdf_path,
        "front_matter": front,
        "drawing_sheets": drawings.get("drawing_sheets")
        if isinstance(drawings, dict)
        else drawings,
        "qa": qa,
    }
