from __future__ import annotations

"""
drawing_export.py

Export artifacts (PNGs / PDFs) for drawing sheets using the structured output
from `drawing_segmentation.py`.

Segmentation (drawing_segmentation.py) returns only geometry + metadata.
This module performs all file I/O.

Coordinate conventions
- `BBoxNorm` is normalized to [0,1] with origin at top-left.
- When rendering with PyMuPDF, we rasterize at a caller-selected DPI.
- Cropping is done in pixel coordinates derived from the rendered image.

Diagnostics
- Export never raises for expected issues (missing dependencies, I/O failure).
- It emits `diag.warn`/`diag.error` and returns an ExportResult.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import re

# Import segmentation types
from patent_ingest.diagnostics import Diagnostics
from patent_ingest.drawing_sheets.model import DrawingSheetsData
from patent_ingest.drawing_sheets.segment import BBoxNorm


class ExportStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class ExportPolicy:
    """Controls export behavior."""

    # Rendering resolution for crops
    dpi: int = 200

    # What to export
    export_region_pngs: bool = True
    export_sheet_pngs: bool = False

    # Output subdirs (relative to out_dir)
    region_dirname: str = "regions"
    sheet_dirname: str = "sheets"

    # Crop padding in pixels (applied after bbox->px)
    pad_px: int = 8

    # If True, any error causes FAILED; else PARTIAL where possible.
    strict: bool = False


@dataclass(frozen=True)
class ExportPaths:
    out_dir: str
    region_dir: Optional[str] = None
    sheet_dir: Optional[str] = None


@dataclass(frozen=True)
class ExportResult:
    status: ExportStatus
    paths: ExportPaths
    diagnostics: Diagnostics
    meta: Dict[str, Any] = field(default_factory=dict)


def _try_import_pymupdf():
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except Exception:
        return None


def _bbox_norm_to_px(b: BBoxNorm, W: int, H: int) -> Tuple[int, int, int, int]:
    x0 = int(max(0.0, min(1.0, b.x0)) * W)
    y0 = int(max(0.0, min(1.0, b.y0)) * H)
    x1 = int(max(0.0, min(1.0, b.x1)) * W)
    y1 = int(max(0.0, min(1.0, b.y1)) * H)
    if x1 <= x0:
        x1 = min(W, x0 + 1)
    if y1 <= y0:
        y1 = min(H, y0 + 1)
    return x0, y0, x1, y1


def _pad_px_box(
    box: Tuple[int, int, int, int], W: int, H: int, pad: int
) -> Tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (
        max(0, x0 - pad),
        max(0, y0 - pad),
        min(W, x1 + pad),
        min(H, y1 + pad),
    )


_slug_sanitize_re = re.compile(r"[^a-zA-Z0-9_\-]+")


def _safe_slug(s: str) -> str:
    s = (s or "").strip()
    s = _slug_sanitize_re.sub("_", s)
    return s.strip("_") or "region"


def export_drawing_artifacts(
    drawing: DrawingSheetsData,
    out_dir: str | Path,
    diag: Diagnostics,
    *,
    policy: ExportPolicy = ExportPolicy(),
) -> ExportResult:
    """Export PNG artifacts from segmented drawing sheets.

    The function is intentionally tolerant:
    - If a specific page/region export fails, it records a warning and continues.
    - If a dependency is missing, it records an error and returns FAILED.

    Returns ExportResult with created directories.
    """
    out_dir = str(out_dir)
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    pymupdf = _try_import_pymupdf()
    if pymupdf is None:
        diag.error(
            "drawing_export.pymupdf_missing",
            "PyMuPDF (pymupdf) is required for exporting raster artifacts.",
            field="drawing_export",
        )
        return ExportResult(
            status=ExportStatus.FAILED,
            paths=ExportPaths(out_dir=out_dir),
            diagnostics=diag,
        )

    # Prepare output dirs
    region_dir = None
    sheet_dir = None
    if policy.export_region_pngs:
        region_dir = str(Path(out_dir) / policy.region_dirname)
        Path(region_dir).mkdir(parents=True, exist_ok=True)
    if policy.export_sheet_pngs:
        sheet_dir = str(Path(out_dir) / policy.sheet_dirname)
        Path(sheet_dir).mkdir(parents=True, exist_ok=True)

    had_error = False
    had_warning = False

    try:
        doc = pymupdf.open(drawing.pdf_path)
    except Exception as e:
        diag.error(
            "drawing_export.pdf_open_failed",
            f"Failed to open PDF for exporting: {e}",
            field="drawing_export",
            meta={"pdf_path": drawing.pdf_path},
        )
        return ExportResult(
            status=ExportStatus.FAILED,
            paths=ExportPaths(
                out_dir=out_dir, region_dir=region_dir, sheet_dir=sheet_dir
            ),
            diagnostics=diag,
        )

    def render_page_png(page_index: int, dpi: int) -> tuple[bytes, int, int]:
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=dpi)
        return pix.tobytes("png"), pix.width, pix.height

    # Export per sheet
    for sheet in drawing.sheets:
        p = sheet.page.page_index

        try:
            png_bytes, W, H = render_page_png(p, policy.dpi)
        except Exception as e:
            had_warning = True
            diag.warn(
                "drawing_export.page_render_failed",
                f"Failed to render page {p} at dpi={policy.dpi}: {e}",
                field="drawing_export",
                meta={"page": p, "dpi": policy.dpi},
            )
            continue

        # Optionally export full sheet image
        if policy.export_sheet_pngs and sheet_dir is not None:
            try:
                out_path = Path(sheet_dir) / f"sheet_p{p + 1:04d}_dpi{policy.dpi}.png"
                out_path.write_bytes(png_bytes)
            except Exception as e:
                had_warning = True
                diag.warn(
                    "drawing_export.sheet_write_failed",
                    f"Failed to write sheet PNG for page {p}: {e}",
                    field="drawing_export",
                    meta={"page": p, "out": str(out_path)},
                )

        # Export each region
        if policy.export_region_pngs and region_dir is not None:
            # Need PIL to crop from bytes
            try:
                from PIL import Image  # type: ignore
                import io

                img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
            except Exception as e:
                diag.error(
                    "drawing_export.pil_missing",
                    f"PIL is required to crop PNG bytes: {e}",
                    field="drawing_export",
                )
                had_error = True
                if policy.strict:
                    return ExportResult(
                        status=ExportStatus.FAILED,
                        paths=ExportPaths(
                            out_dir=out_dir, region_dir=region_dir, sheet_dir=sheet_dir
                        ),
                        diagnostics=diag,
                    )
                continue

            for idx, region in enumerate(sheet.regions):
                try:
                    box = _bbox_norm_to_px(region.crop_bbox_norm, W, H)
                    box = _pad_px_box(box, W, H, policy.pad_px)
                    crop = img.crop(box)

                    # Stable-ish name: figure slug if available
                    slug = region.fig.slug if region.fig else f"r{idx + 1}"
                    slug = _safe_slug(slug)

                    out_path = (
                        Path(region_dir) / f"p{p + 1:04d}_{slug}_dpi{policy.dpi}.png"
                    )
                    crop.save(out_path)
                except Exception as e:
                    had_warning = True
                    diag.warn(
                        "drawing_export.region_write_failed",
                        f"Failed to export region on page {p}: {e}",
                        field="drawing_export",
                        meta={"page": p, "region_index": idx},
                    )

    if policy.strict and (had_error or getattr(diag, "errors", None)):
        return ExportResult(
            status=ExportStatus.FAILED,
            paths=ExportPaths(
                out_dir=out_dir, region_dir=region_dir, sheet_dir=sheet_dir
            ),
            diagnostics=diag,
        )

    # Prefer PARTIAL if any warnings/errors occurred
    if had_error or (getattr(diag, "errors", None) and diag.errors):
        status = ExportStatus.PARTIAL
    elif had_warning or (getattr(diag, "warnings", None) and diag.warnings):
        status = ExportStatus.PARTIAL
    else:
        status = ExportStatus.OK

    return ExportResult(
        status=status,
        paths=ExportPaths(out_dir=out_dir, region_dir=region_dir, sheet_dir=sheet_dir),
        diagnostics=diag,
        meta={"pdf_path": drawing.pdf_path, "dpi": policy.dpi},
    )
