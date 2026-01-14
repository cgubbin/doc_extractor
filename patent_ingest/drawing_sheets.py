from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

from pypdf import PdfReader, PdfWriter


# ============================================================
# Regex patterns
# ============================================================

_SHEET_OF_RE = re.compile(
    r"\bSheet\s+([0-9A-Za-z]+)\s+of\s+([0-9]+)\b",
    re.IGNORECASE,
)

_FIG_TOKEN_RE = re.compile(r"^(?:Fig\.?|FIG\.?)$", re.IGNORECASE)
_FIG_COMBINED_RE = re.compile(r"^(?:Fig\.?|FIG\.?)([0-9]+[A-Za-z]?)$", re.IGNORECASE)
_FIG_NUM_RE = re.compile(r"^([0-9]+[A-Za-z]?)$")


# ============================================================
# QA warning keys
# ============================================================

W_PAGE_RANGE_OOB = "drawing_sheets_page_range_out_of_bounds"
W_COUNT_MISMATCH = "drawing_sheets_count_mismatch"
W_EXPORT_FAILED = "drawing_sheet_export_failed"

W_HEURISTIC_MISMATCH = "drawing_sheets_heuristic_mismatch"

W_FIGURES_NO_OCR = "drawing_figures_enabled_but_no_ocr"
W_FIGURES_OCR_FAILED = "drawing_figures_ocr_failed"
W_FIGURES_NONE_ON_SHEET_PREFIX = "drawing_figures_none_on_sheet_"


# ============================================================
# OCR helpers
# ============================================================


@dataclass
class _FigureItem:
    label: str
    bbox_norm: List[float]  # [x0, y0, x1, y1] in [0,1]
    confidence: Optional[float]


def _try_import_ocr_stack():
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
        import io

        return pymupdf, pytesseract, Image, io
    except Exception:
        return None


def _ocr_detect_figures_on_page(
    *,
    pdf_path: str,
    pdf_page_index: int,
    dpi: int,
) -> Tuple[List[_FigureItem], Optional[str]]:
    stack = _try_import_ocr_stack()
    if stack is None:
        return [], "ocr_stack_unavailable"

    pymupdf, pytesseract, Image, io = stack

    try:
        doc = pymupdf.open(pdf_path)
        page = doc.load_page(pdf_page_index)
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        W, H = img.size

        data = pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            config="--oem 3 --psm 6",
        )

        tokens = []
        for i, t in enumerate(data.get("text", [])):
            t = (t or "").strip()
            if not t:
                continue
            conf = float(data["conf"][i]) if data["conf"][i] != "-1" else -1.0
            tokens.append(
                {
                    "t": t,
                    "conf": conf,
                    "x": int(data["left"][i]),
                    "y": int(data["top"][i]),
                    "w": int(data["width"][i]),
                    "h": int(data["height"][i]),
                }
            )

        found: Dict[str, Dict[str, Any]] = {}

        # Combined: Fig.3A
        for tok in tokens:
            m = _FIG_COMBINED_RE.fullmatch(tok["t"])
            if m:
                lab = m.group(1).upper()
                found[lab] = {
                    "conf": tok["conf"],
                    "x0": tok["x"],
                    "y0": tok["y"],
                    "x1": tok["x"] + tok["w"],
                    "y1": tok["y"] + tok["h"],
                }

        # Split: Fig. + 3A
        fig_tokens = [t for t in tokens if _FIG_TOKEN_RE.fullmatch(t["t"])]
        num_tokens = [t for t in tokens if _FIG_NUM_RE.fullmatch(t["t"])]

        for f in fig_tokens:
            f_cy = f["y"] + f["h"] / 2
            for n in num_tokens:
                if abs((n["y"] + n["h"] / 2) - f_cy) <= max(12, f["h"]):
                    dx = n["x"] - (f["x"] + f["w"])
                    if 0 <= dx <= 220:
                        lab = n["t"].upper()
                        conf = min(f["conf"], n["conf"])
                        if lab not in found or conf > found[lab]["conf"]:
                            found[lab] = {
                                "conf": conf,
                                "x0": min(f["x"], n["x"]),
                                "y0": min(f["y"], n["y"]),
                                "x1": max(f["x"] + f["w"], n["x"] + n["w"]),
                                "y1": max(f["y"] + f["h"], n["y"] + n["h"]),
                            }

        items: List[_FigureItem] = []
        for lab, d in found.items():
            items.append(
                _FigureItem(
                    label=lab,
                    bbox_norm=[
                        d["x0"] / W,
                        d["y0"] / H,
                        d["x1"] / W,
                        d["y1"] / H,
                    ],
                    confidence=None if d["conf"] < 0 else min(1.0, d["conf"] / 100.0),
                )
            )

        return items, None

    except Exception as e:
        return [], f"ocr_exception:{type(e).__name__}"


# ============================================================
# Public API
# ============================================================


def process_drawing_sheets(
    pdf_path: str,
    *,
    drawing_sheets_expected: int,
    first_drawing_sheet_index: int,
    output_dir: Optional[str] = None,
    export_pdf: bool = True,
    detect_figures: bool = False,
    figure_ocr_dpi: int = 200,
    max_pages_scan: int = 10,
) -> Dict[str, Any]:
    """
    Phase 1 drawing-sheet processing.

    Parameters
    ----------
    drawing_sheets_expected : int
        Authoritative number of drawing sheets (from front matter).
    first_drawing_sheet_index : int
        0-based index of the first drawing sheet in the source PDF.

    Heuristics are used only for validation, never selection.
    """

    qa_warnings: List[str] = []
    qa_info: Dict[str, Any] = {}

    reader = PdfReader(pdf_path)
    pdf_num_pages = len(reader.pages)

    start = first_drawing_sheet_index
    end_exclusive = start + drawing_sheets_expected

    if end_exclusive > pdf_num_pages:
        qa_warnings.append(W_PAGE_RANGE_OOB)
        end_exclusive = pdf_num_pages

    sheet_page_indices = list(range(start, end_exclusive))
    sheet_count = len(sheet_page_indices)

    if sheet_count != drawing_sheets_expected:
        qa_warnings.append(W_COUNT_MISMATCH)
        qa_info["expected_sheet_count"] = drawing_sheets_expected
        qa_info["actual_sheet_count"] = sheet_count

    # --------------------------------------------------------
    # Heuristic validation (non-authoritative)
    # --------------------------------------------------------

    heuristic_hits = []
    for i in range(start, min(start + max_pages_scan, pdf_num_pages)):
        text = reader.pages[i].extract_text() or ""
        if _SHEET_OF_RE.search(text):
            heuristic_hits.append(i)

    if heuristic_hits and heuristic_hits[:sheet_count] != sheet_page_indices:
        qa_warnings.append(W_HEURISTIC_MISMATCH)
        qa_info["heuristic_sheet_page_indices"] = heuristic_hits

    # --------------------------------------------------------
    # Export setup
    # --------------------------------------------------------

    export_base: Optional[Path] = None
    if output_dir and export_pdf:
        export_base = Path(output_dir)
        (export_base / "sheets").mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # Figure detection availability
    # --------------------------------------------------------

    figure_count_total: Optional[int] = 0 if detect_figures else None

    if detect_figures and _try_import_ocr_stack() is None:
        qa_warnings.append(W_FIGURES_NO_OCR)
        detect_figures = False
        figure_count_total = None

    sheets: List[Dict[str, Any]] = []

    for sheet_index, pdf_page_index in enumerate(sheet_page_indices):
        page = reader.pages[pdf_page_index]

        export_pdf_path = None
        if export_base:
            try:
                writer = PdfWriter()
                writer.add_page(page)
                p = export_base / "sheets" / f"sheet_{sheet_index + 1:03d}.pdf"
                with open(p, "wb") as f:
                    writer.write(f)
                export_pdf_path = str(p)
            except Exception:
                qa_warnings.append(W_EXPORT_FAILED)

        figures_block = {"enabled": bool(detect_figures), "count": None, "items": []}

        if detect_figures:
            items, err = _ocr_detect_figures_on_page(
                pdf_path=pdf_path,
                pdf_page_index=pdf_page_index,
                dpi=figure_ocr_dpi,
            )
            if err:
                qa_warnings.append(W_FIGURES_OCR_FAILED)
                figures_block["count"] = 0
            else:
                figures_block["items"] = [
                    {
                        "label": it.label,
                        "bbox_norm": it.bbox_norm,
                        "confidence": it.confidence,
                    }
                    for it in items
                ]
                figures_block["count"] = len(items)
                figure_count_total += len(items)

                if not items:
                    qa_warnings.append(f"{W_FIGURES_NONE_ON_SHEET_PREFIX}{sheet_index}")

        sheets.append(
            {
                "sheet_index": sheet_index,
                "pdf_page_index": pdf_page_index,
                "export": {"pdf_path": export_pdf_path, "png_path": None},
                "figures": figures_block,
            }
        )

    return {
        "drawing_sheets": {
            "expected_sheet_count": drawing_sheets_expected,
            "sheet_count": sheet_count,
            "sheet_page_indices": sheet_page_indices,
            "sheets": sheets,
            "figure_count_total": figure_count_total,
        },
        "qa": {
            "warnings": qa_warnings,
            "info": {
                **qa_info,
                "pdf_num_pages": pdf_num_pages,
                "first_drawing_sheet_index": first_drawing_sheet_index,
                "figures_enabled": detect_figures,
            },
        },
    }


def canonical_drawing_sheets(result: Dict[str, Any]) -> Dict[str, Any]:
    ds = result["drawing_sheets"]

    out = {
        "expected_sheet_count": ds["expected_sheet_count"],
        "sheet_count": ds["sheet_count"],
        "sheet_page_indices": ds["sheet_page_indices"],
    }

    if ds.get("figure_count_total") is not None:
        out["figure_count_total"] = ds["figure_count_total"]

    return out
