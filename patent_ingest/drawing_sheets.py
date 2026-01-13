from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from pypdf import PdfReader, PdfWriter


# ----------------------------
# Public API
# ----------------------------


def process_drawing_sheets(
    pdf_path: str,
    *,
    front_matter: dict,
    drawings_start_index: int | None = None,
    output_dir: Optional[str] = None,
    export_pdf: bool = True,
    export_png: bool = False,
    segment_drawings: bool = False,
    max_pages_scan: int = 10,
) -> Dict[str, Any]:
    """
    Extract and (optionally) segment drawing sheets.

    Phase 1:
      * Select drawing sheet page range using front-matter expected count.
      * Export one-PDF-per-sheet if requested.
      * Return stable metadata + QA diagnostics.

    Phase 2 (stubbed):
      * Drawing segmentation interface only; no renderer yet.
    """

    qa_warnings: List[str] = []
    qa_info: Dict[str, Any] = {}

    reader = PdfReader(pdf_path)
    pdf_num_pages = len(reader.pages)

    expected_sheet_count = front_matter["reported_counts"]["reported_drawing_sheet_count"]

    front_page_index = 0

    # Some pipelines scan more than one front-matter page
    front_matter_pages_scanned = drawings_start_index

    if expected_sheet_count is None:
        qa_warnings.append("drawing_sheets_expected_missing")

    # Drawing sheets are assumed to start immediately after front matter
    start_index = (
        drawings_start_index
        if drawings_start_index
        else front_page_index + front_matter_pages_scanned
    )

    sheet_page_indices: List[int] = []
    if expected_sheet_count:
        end_index = start_index + expected_sheet_count
        if end_index > pdf_num_pages:
            qa_warnings.append("drawing_sheets_page_range_out_of_bounds")
            end_index = pdf_num_pages
        sheet_page_indices = list(range(start_index, end_index))
    else:
        sheet_page_indices = []

    sheet_count = len(sheet_page_indices)

    if expected_sheet_count is not None and sheet_count != expected_sheet_count:
        qa_warnings.append("drawing_sheets_count_mismatch")
        qa_info["expected_sheet_count"] = expected_sheet_count
        qa_info["actual_sheet_count"] = sheet_count

    sheets: List[Dict[str, Any]] = []

    export_base: Optional[Path] = None
    if output_dir:
        export_base = Path(output_dir)
        if export_pdf:
            (export_base / "sheets").mkdir(parents=True, exist_ok=True)

    for sheet_index, pdf_page_index in enumerate(sheet_page_indices):
        page = reader.pages[pdf_page_index]

        export_pdf_path: Optional[str] = None
        if export_base and export_pdf:
            try:
                writer = PdfWriter()
                writer.add_page(page)
                fname = f"sheet_{sheet_index + 1:03d}.pdf"
                out_path = export_base / "sheets" / fname
                with open(out_path, "wb") as f:
                    writer.write(f)
                export_pdf_path = str(out_path)
            except Exception:
                qa_warnings.append("drawing_sheet_export_failed")

        if export_png:
            qa_warnings.append("drawing_segmentation_enabled_but_no_renderer")

        segmentation_block = {
            "enabled": bool(segment_drawings),
            "drawing_count": None,
            "drawings": [],
        }

        if segment_drawings:
            qa_warnings.append("drawing_segmentation_enabled_but_no_renderer")

        sheets.append(
            {
                "sheet_index": sheet_index,
                "pdf_page_index": pdf_page_index,
                "export": {
                    "pdf_path": export_pdf_path,
                    "png_path": None,
                },
                "page_size_points": None,
                "segmentation": segmentation_block,
            }
        )

    drawing_count_total = None
    if segment_drawings:
        drawing_count_total = None

    result = {
        "drawing_sheets": {
            "expected_sheet_count": expected_sheet_count,
            "sheet_count": sheet_count,
            "sheet_page_indices": sheet_page_indices,
            "sheets": sheets,
            "drawing_count_total": drawing_count_total,
        },
        "qa": {
            "warnings": qa_warnings,
            "info": {
                **qa_info,
                "pdf_num_pages": pdf_num_pages,
                "export_dir": output_dir,
                "segmentation_enabled": segment_drawings,
            },
        },
    }

    return result


def canonical_drawing_sheets(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonicalize drawing-sheet output for golden tests.

    Excludes volatile fields such as export paths and page sizes.
    """
    ds = result.get("drawing_sheets", {})

    canonical: Dict[str, Any] = {
        "expected_sheet_count": ds.get("expected_sheet_count"),
        "sheet_count": ds.get("sheet_count"),
        "sheet_page_indices": ds.get("sheet_page_indices"),
    }

    if ds.get("drawing_count_total") is not None:
        canonical["drawing_count_total"] = ds.get("drawing_count_total")

    return canonical
