from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re


# ============================================================
# Regex patterns
# ============================================================

_SHEET_OF_RE = re.compile(r"\bSheet\s+([0-9A-Za-z]+)\s+of\s+([0-9]+)\b", re.IGNORECASE)

_FIG_TOKEN_RE = re.compile(
    r"^(?:Fig\.?|FIG\.?)$", re.IGNORECASE
)  # Fig, Fig., FIG, FIG.
_FIG_WORD_RE = re.compile(r"^Fig$", re.IGNORECASE)  # Fig
_FIG_COMBINED_RE = re.compile(
    r"^(?:Fig\.?|FIG\.?)([0-9]+[A-Za-z]?)$", re.IGNORECASE
)  # Fig.3A
_FIG_NUM_RE = re.compile(r"^([0-9]+[A-Za-z]?)$")  # 3, 3A
_FIG_ID_RE = re.compile(r"^(\d+)([A-Za-z])?$")  # 3A -> (3,"A")


# ============================================================
# QA warning keys
# ============================================================

W_PAGE_RANGE_OOB = "drawing_sheets_page_range_out_of_bounds"
W_COUNT_MISMATCH = "drawing_sheets_count_mismatch"
W_EXPORT_PDF_FAILED = "drawing_sheet_export_failed"

W_EXPORT_PNG_NO_RENDERER = "drawing_sheet_png_export_no_renderer"
W_EXPORT_PNG_FAILED = "drawing_sheet_png_export_failed"

W_EXPORT_FIG_PNG_MISSING_DEPS = "drawing_fig_png_export_missing_deps"
W_EXPORT_FIG_PNG_FAILED = "drawing_fig_png_export_failed"

W_OPENCV_MISSING = "drawing_fig_png_opencv_missing"
W_OPENCV_COMPONENTS_FAILED = "drawing_fig_png_opencv_components_failed"
W_OPENCV_NO_COMPONENTS = "drawing_fig_png_opencv_no_components"
W_OPENCV_NO_COMPONENTS_FOR_FIG_PREFIX = "drawing_fig_png_opencv_no_components_for_fig_"
W_OPENCV_FALLBACK_EXPANDED_PREFIX = "drawing_fig_png_fallback_expanded_for_fig_"

W_HEURISTIC_MISMATCH = "drawing_sheets_heuristic_mismatch"

W_FIGURES_NO_PYMUPDF = "drawing_figures_enabled_but_pymupdf_missing"
W_FIGURES_OCR_UNAVAILABLE = "drawing_figures_ocr_unavailable"
W_FIGURES_OCR_FAILED = "drawing_figures_ocr_failed"
W_FIGURES_NONE_ON_SHEET_PREFIX = "drawing_figures_none_on_sheet_"

W_FIGURES_TEXT_USED_PREFIX = "drawing_figures_text_used_on_sheet_"
W_FIGURES_OCR_USED_PREFIX = "drawing_figures_ocr_used_on_sheet_"


# ============================================================
# Figure models
# ============================================================


@dataclass
class _FigureItem:
    label: str
    figure_number: int
    subfigure_id: Optional[str]
    label_bbox_norm: List[float]  # label bbox [x0,y0,x1,y1] norm coords
    confidence: Optional[float]
    source: str  # "text" or "ocr"


def parse_figure_id(label: str) -> Optional[Tuple[int, Optional[str]]]:
    m = _FIG_ID_RE.fullmatch((label or "").strip())
    if not m:
        return None
    num = int(m.group(1))
    sub = m.group(2).upper() if m.group(2) else None
    return num, sub


def _stable_figure_sort_key(r: Dict[str, Any]) -> Tuple[int, str, int]:
    return (
        int(r["figure_number"]),
        "" if r.get("subfigure_id") is None else str(r["subfigure_id"]),
        int(r["sheet_index"]),
    )


def _figure_slug(figure_number: int, subfigure_id: Optional[str]) -> str:
    return f"{figure_number}{'' if subfigure_id is None else subfigure_id.lower()}"


# ============================================================
# Optional stacks
# ============================================================


def _try_import_pymupdf():
    try:
        import pymupdf

        return pymupdf
    except Exception:
        return None


def _try_import_ocr_stack():
    """
    OCR stack is optional: pymupdf + pytesseract + PIL
    """
    try:
        import pymupdf
        import pytesseract
        from PIL import Image
        import io

        return pymupdf, pytesseract, Image, io
    except Exception:
        return None


def _try_import_pil():
    try:
        from PIL import Image

        return Image
    except Exception:
        return None


def _try_import_cv2():
    try:
        import cv2  # type: ignore

        return cv2
    except Exception:
        return None


# ============================================================
# Phase 2: PNG rendering
# ============================================================


def _render_page_png(
    *, pymupdf_doc, pdf_page_index: int, out_path: Path, dpi: int
) -> None:
    page = pymupdf_doc.load_page(pdf_page_index)
    pix = page.get_pixmap(dpi=dpi)
    pix.save(str(out_path))


# ============================================================
# Geometry helpers
# ============================================================


def _norm_to_px(b: List[float], W: int, H: int) -> Tuple[int, int, int, int]:
    x0, y0, x1, y1 = b
    px0 = int(max(0.0, min(1.0, x0)) * W)
    py0 = int(max(0.0, min(1.0, y0)) * H)
    px1 = int(max(0.0, min(1.0, x1)) * W)
    py1 = int(max(0.0, min(1.0, y1)) * H)
    if px1 <= px0:
        px1 = min(W, px0 + 1)
    if py1 <= py0:
        py1 = min(H, py0 + 1)
    return px0, py0, px1, py1


def _px_to_norm(px: Tuple[int, int, int, int], W: int, H: int) -> List[float]:
    x0, y0, x1, y1 = px
    return [
        max(0.0, min(1.0, x0 / float(W))),
        max(0.0, min(1.0, y0 / float(H))),
        max(0.0, min(1.0, x1 / float(W))),
        max(0.0, min(1.0, y1 / float(H))),
    ]


def _expand_box(
    b: Tuple[int, int, int, int], W: int, H: int, margin: int
) -> Tuple[int, int, int, int]:
    x0, y0, x1, y1 = b
    return (
        max(0, x0 - margin),
        max(0, y0 - margin),
        min(W, x1 + margin),
        min(H, y1 + margin),
    )


def _centroid(b: Tuple[int, int, int, int]) -> Tuple[float, float]:
    x0, y0, x1, y1 = b
    return (0.5 * (x0 + x1), 0.5 * (y0 + y1))


def _area(b: Tuple[int, int, int, int]) -> int:
    x0, y0, x1, y1 = b
    return max(0, x1 - x0) * max(0, y1 - y0)


def _union_boxes(
    boxes: List[Tuple[int, int, int, int]],
) -> Optional[Tuple[int, int, int, int]]:
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    return (x0, y0, x1, y1)


def _sqdist(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def _intersect_area(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> int:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0
    return (ix1 - ix0) * (iy1 - iy0)


def _overlaps_label(
    component: Tuple[int, int, int, int],
    label_box: Tuple[int, int, int, int],
    min_overlap_frac: float = 0.10,
) -> bool:
    """
    Treat a component as caption ink if overlap(component,label)/area(component) is large enough.
    Using overlap fraction of the component area is more stable for text than true IoU.
    """
    a = _area(component)
    if a <= 0:
        return False
    inter = _intersect_area(component, label_box)
    return (inter / float(a)) >= min_overlap_frac


# ============================================================
# Partition helper (still used as last-resort fallback)
# ============================================================


def _label_center_norm(b: List[float]) -> Tuple[float, float]:
    x0, y0, x1, y1 = b
    return (0.5 * (x0 + x1), 0.5 * (y0 + y1))


def _compute_partition_boxes_norm(
    centers: List[Tuple[float, float]],
) -> List[List[float]]:
    """
    Rectangular Voronoi-like partition from label centers.
    Returns N boxes in norm coords.
    """
    n = len(centers)
    out: List[List[float]] = []
    for i in range(n):
        xi, yi = centers[i]
        left = [x for (x, _) in centers if x < xi]
        right = [x for (x, _) in centers if x > xi]
        up = [y for (_, y) in centers if y < yi]
        down = [y for (_, y) in centers if y > yi]

        x0 = 0.0 if not left else 0.5 * (max(left) + xi)
        x1 = 1.0 if not right else 0.5 * (min(right) + xi)
        y0 = 0.0 if not up else 0.5 * (max(up) + yi)
        y1 = 1.0 if not down else 0.5 * (min(down) + yi)

        x0 = max(0.0, min(1.0, x0))
        x1 = max(0.0, min(1.0, x1))
        y0 = max(0.0, min(1.0, y0))
        y1 = max(0.0, min(1.0, y1))

        if x1 <= x0:
            x0, x1 = max(0.0, xi - 0.25), min(1.0, xi + 0.25)
        if y1 <= y0:
            y0, y1 = max(0.0, yi - 0.25), min(1.0, yi + 0.25)

        out.append([x0, y0, x1, y1])

    return out


# ============================================================
# OpenCV component extraction + merging
# ============================================================


def _estimate_header_cut_y(
    boxes: List[Tuple[int, int, int, int]], W: int, H: int
) -> int:
    """
    Return a y threshold above which to ignore components/crops (header region).
    Heuristic: look for wide boxes in top quarter of the page; take the max y1 among them.
    """
    if not boxes:
        return int(0.10 * H)

    top_limit = int(0.25 * H)
    candidates = []
    for x0, y0, x1, y1 in boxes:
        if y1 > top_limit:
            continue
        w = x1 - x0
        h = y1 - y0
        # wide-ish header ink, not the drawing
        if w >= 0.45 * W and h <= 0.18 * H:
            candidates.append((x0, y0, x1, y1))

    if not candidates:
        return int(0.10 * H)

    return min(H, max(y1 for (_x0, _y0, _x1, y1) in candidates) + int(0.01 * H))


def _merge_boxes(
    boxes: List[Tuple[int, int, int, int]], max_gap: int
) -> List[Tuple[int, int, int, int]]:
    """
    Merge overlapping or near-overlapping boxes by iterative union.
    Boxes are in pixel coords.
    """
    if not boxes:
        return []
    boxes = boxes[:]
    merged = True
    while merged:
        merged = False
        out: List[Tuple[int, int, int, int]] = []
        used = [False] * len(boxes)

        for i, a in enumerate(boxes):
            if used[i]:
                continue
            cur = a
            used[i] = True

            changed = True
            while changed:
                changed = False
                cx0, cy0, cx1, cy1 = cur
                ex0, ey0, ex1, ey1 = (
                    cx0 - max_gap,
                    cy0 - max_gap,
                    cx1 + max_gap,
                    cy1 + max_gap,
                )
                for j, b in enumerate(boxes):
                    if used[j]:
                        continue
                    bx0, by0, bx1, by1 = b
                    overlaps = not (bx1 < ex0 or bx0 > ex1 or by1 < ey0 or by0 > ey1)
                    if overlaps:
                        cur = (
                            min(cx0, bx0),
                            min(cy0, by0),
                            max(cx1, bx1),
                            max(cy1, by1),
                        )
                        used[j] = True
                        changed = True
                        merged = True

            out.append(cur)

        boxes = out

    return boxes


def _extract_ink_components(
    *,
    cv2,
    sheet_bgr,
    min_area_px: int,
    canny1: int,
    canny2: int,
    dilate_iter: int,
    merge_gap_px: int,
) -> List[Tuple[int, int, int, int]]:
    """
    Extract ink components as bounding boxes from a sheet image (full sheet).
    """
    gray = cv2.cvtColor(sheet_bgr, cv2.COLOR_BGR2GRAY)

    edges = cv2.Canny(gray, canny1, canny2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.dilate(edges, kernel, iterations=dilate_iter)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes: List[Tuple[int, int, int, int]] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < float(min_area_px):
            continue
        x, y, w, h = cv2.boundingRect(c)
        boxes.append((x, y, x + w, y + h))

    boxes = _merge_boxes(boxes, max_gap=merge_gap_px)
    return boxes


# ============================================================
# Figure detection (text-first + OCR fallback)
# ============================================================


def _detect_figures_from_text_words(
    *, pymupdf_doc, pdf_page_index: int
) -> List[_FigureItem]:
    page = pymupdf_doc.load_page(pdf_page_index)
    rect = page.rect
    W, H = float(rect.width), float(rect.height)

    words = page.get_text("words") or []

    from collections import defaultdict

    lines = defaultdict(list)
    for x0, y0, x1, y1, w, block, line, wn in words:
        txt = (w or "").strip()
        if not txt:
            continue
        lines[(block, line)].append(
            (float(x0), float(y0), float(x1), float(y1), str(txt))
        )

    found: Dict[str, Tuple[float, float, float, float]] = {}

    def add(label: str, bbox: Tuple[float, float, float, float]) -> None:
        if label not in found:
            found[label] = bbox

    for (_block, _line), toks in lines.items():
        toks_sorted = sorted(toks, key=lambda t: t[0])

        for idx, t in enumerate(toks_sorted):
            w = t[4]

            m = _FIG_COMBINED_RE.fullmatch(w)
            if m:
                lab = m.group(1).upper()
                add(lab, (t[0], t[1], t[2], t[3]))
                continue

            if _FIG_TOKEN_RE.fullmatch(w) or _FIG_WORD_RE.fullmatch(w):
                j = idx + 1
                if j < len(toks_sorted) and toks_sorted[j][4] == ".":
                    j += 1
                if j < len(toks_sorted) and _FIG_NUM_RE.fullmatch(toks_sorted[j][4]):
                    n = toks_sorted[j]
                    lab = n[4].upper()
                    x0 = min(t[0], n[0])
                    y0 = min(t[1], n[1])
                    x1 = max(t[2], n[2])
                    y1 = max(t[3], n[3])
                    add(lab, (x0, y0, x1, y1))

    items: List[_FigureItem] = []
    for lab, (x0, y0, x1, y1) in found.items():
        parsed = parse_figure_id(lab)
        if parsed is None:
            continue
        fig_num, sub = parsed
        bbox_norm = [
            max(0.0, min(1.0, x0 / W)),
            max(0.0, min(1.0, y0 / H)),
            max(0.0, min(1.0, x1 / W)),
            max(0.0, min(1.0, y1 / H)),
        ]
        items.append(
            _FigureItem(
                label=lab,
                figure_number=fig_num,
                subfigure_id=sub,
                label_bbox_norm=bbox_norm,
                confidence=None,
                source="text",
            )
        )

    items.sort(
        key=lambda it: (
            it.figure_number,
            "" if it.subfigure_id is None else it.subfigure_id,
        )
    )
    return items


def _detect_figures_from_ocr(
    *, pdf_path: str, pdf_page_index: int, dpi: int
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

        fig_tokens = [
            t
            for t in tokens
            if _FIG_TOKEN_RE.fullmatch(t["t"]) or _FIG_WORD_RE.fullmatch(t["t"])
        ]
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
            parsed = parse_figure_id(lab)
            if parsed is None:
                continue
            fig_num, sub = parsed
            bbox_norm = [
                max(0.0, min(1.0, d["x0"] / W)),
                max(0.0, min(1.0, d["y0"] / H)),
                max(0.0, min(1.0, d["x1"] / W)),
                max(0.0, min(1.0, d["y1"] / H)),
            ]
            items.append(
                _FigureItem(
                    label=lab,
                    figure_number=fig_num,
                    subfigure_id=sub,
                    label_bbox_norm=bbox_norm,
                    confidence=None if d["conf"] < 0 else min(1.0, d["conf"] / 100.0),
                    source="ocr",
                )
            )

        items.sort(
            key=lambda it: (
                it.figure_number,
                "" if it.subfigure_id is None else it.subfigure_id,
            )
        )
        return items, None

    except Exception as e:
        return [], f"ocr_exception:{type(e).__name__}"


# ============================================================
# Main entry point
# ============================================================

from patent_ingest.diagnostics import Diagnostics


@dataclass(frozen=True)
class PDFPageRef:
    pdf_path: str
    page_index: int  # 0-based PDF page index


@dataclass(frozen=True)
class BBox:
    # PDF coordinates in points (same as pdfplumber / pdfminer): (x0,y0) bottom-left, (x1,y1) top-right
    x0: float
    y0: float
    x1: float
    y1: float

    def area(self) -> float:
        return max(0.0, self.x1 - self.x0) * max(0.0, self.y1 - self.y0)


@dataclass(frozen=True)
class RenderInfo:
    dpi: int
    width_px: int
    height_px: int


@dataclass(frozen=True)
class BBoxNorm:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class FigureLabel:
    raw: str
    slug: str
    figure_number: int
    subfigure_id: Optional[str]
    confidence: Optional[float]
    source: str  # "text" | "ocr"


@dataclass(frozen=True)
class DrawingRegionMeta:
    region_index: int
    method: str  # "opencv-cc+label"
    confidence: float
    header_cut_y_px: int
    used_partition_fallback: bool
    used_radius_fallback: bool


@dataclass(frozen=True)
class DrawingRegion:
    page: PDFPageRef
    crop_bbox_norm: BBoxNorm
    fig: Optional[FigureLabel]
    meta: DrawingRegionMeta


@dataclass(frozen=True)
class SheetParse:
    page: PDFPageRef
    render: RenderInfo
    regions: Tuple[DrawingRegion, ...]
    meta: Dict[str, Any]


def _segment_drawings_on_page(
    pdf_path: str,
    pdf_page_index: int,
    diag: "Diagnostics",
    *,
    # --- figure detection ---
    detect_figures: bool = True,
    figure_text_first: bool = True,
    figure_ocr_fallback: bool = True,
    figure_ocr_dpi: int = 200,
    # --- rendering dpi for segmentation ---
    png_dpi: int = 200,
    # --- OpenCV segmentation options (same as before) ---
    use_opencv: bool = True,
    opencv_canny1: int = 50,
    opencv_canny2: int = 150,
    opencv_dilate_iter: int = 2,
    opencv_min_area_px: int = 900,
    opencv_merge_gap_px: int = 12,
    opencv_crop_margin_px: int = 12,
    # --- assignment/crop stabilization (same as before) ---
    label_exclusion_pad_px: int = 12,
    assign_prefer_above_label: bool = True,
    assign_below_penalty: float = 3.0,
    assign_label_overlap_penalty: float = 5.0,
    min_crop_area_frac: float = 0.02,
    fallback_radius_frac: float = 0.60,
) -> SheetParse:
    """
    Single-sheet drawing segmentation:
      - renders page to a raster image (PIL) via PyMuPDF
      - detects figure labels (text-first + OCR fallback)
      - segments ink components via OpenCV and assigns to labels
      - returns per-figure crop bounding boxes (normalized) + typed metadata

    No exporting, no QA dicts: diagnostics replaces warnings/errors.

    Raises only on truly catastrophic failures (e.g. cannot open/render the page at all).
    """
    field = "drawing_segmentation"

    # ---- dependency checks ----
    pymupdf = _try_import_pymupdf()
    if pymupdf is None:
        diag.error(
            "drawing_segmentation.pymupdf_missing",
            "PyMuPDF is required to render pages for drawing segmentation.",
            field=field,
            meta={"pdf_path": pdf_path},
        )
        raise RuntimeError("PyMuPDF missing")

    PILImage = _try_import_pil()
    if PILImage is None:
        diag.error(
            "drawing_segmentation.pil_missing",
            "PIL is required for image-based drawing segmentation.",
            field=field,
        )
        raise RuntimeError("PIL missing")

    cv2 = _try_import_cv2() if use_opencv else None
    if use_opencv and cv2 is None:
        diag.warn(
            "drawing_segmentation.opencv_missing",
            "OpenCV requested but not available; segmentation quality may degrade.",
            field=field,
        )
        use_opencv = False

    # ---- open + render ----
    try:
        doc = pymupdf.open(pdf_path)
        page = doc.load_page(pdf_page_index)
        pix = page.get_pixmap(dpi=png_dpi)
        # pix samples are in RGB by default for PyMuPDF >= 1.22; safe route: use PNG bytes -> PIL
        png_bytes = pix.tobytes("png")
        import io

        img = PILImage.open(io.BytesIO(png_bytes)).convert("RGB")
        Wpx, Hpx = img.size
        render = RenderInfo(dpi=png_dpi, width_px=Wpx, height_px=Hpx)
    except Exception as e:
        diag.error(
            "drawing_segmentation.render_failed",
            f"Failed to render page {pdf_page_index}: {e}",
            field=field,
            meta={"pdf_path": pdf_path, "page_index": pdf_page_index, "dpi": png_dpi},
        )
        raise

    page_ref = PDFPageRef(pdf_path=pdf_path, page_index=pdf_page_index)

    # ---- detect figures (reusing your existing routines) ----
    figure_items: List[_FigureItem] = []
    used_source: Optional[str] = None

    if detect_figures and figure_text_first:
        try:
            figure_items = _detect_figures_from_text_words(
                pymupdf_doc=doc, pdf_page_index=pdf_page_index
            )
            if figure_items:
                used_source = "text"
                diag.info_msg(
                    "drawing_segmentation.figures_text_used",
                    "Detected figure labels from embedded text.",
                    field=field,
                    meta={"page_index": pdf_page_index, "count": len(figure_items)},
                )
        except Exception as e:
            diag.warn(
                "drawing_segmentation.figures_text_failed",
                f"Figure text detection failed: {e}",
                field=field,
                meta={"page_index": pdf_page_index},
            )

    if detect_figures and (not figure_items) and figure_ocr_fallback:
        items_ocr, err = _detect_figures_from_ocr(
            pdf_path=pdf_path, pdf_page_index=pdf_page_index, dpi=figure_ocr_dpi
        )
        if err == "ocr_stack_unavailable":
            diag.warn(
                "drawing_segmentation.figures_ocr_unavailable",
                "OCR figure detection requested but OCR stack is unavailable.",
                field=field,
            )
        elif err is not None:
            diag.warn(
                "drawing_segmentation.figures_ocr_failed",
                f"OCR figure detection failed ({err}).",
                field=field,
                meta={"page_index": pdf_page_index},
            )
        else:
            figure_items = items_ocr
            used_source = "ocr" if figure_items else None
            if figure_items:
                diag.info_msg(
                    "drawing_segmentation.figures_ocr_used",
                    "Detected figure labels via OCR fallback.",
                    field=field,
                    meta={"page_index": pdf_page_index, "count": len(figure_items)},
                )

    if detect_figures and not figure_items:
        diag.warn(
            "drawing_segmentation.figures_none",
            "Figure detection enabled but no figure labels were found on the sheet.",
            field=field,
            meta={"page_index": pdf_page_index},
        )

    # If you want “one big region per page” when figure detection is off,
    # you can add that later. For now, consistent with your prior logic: no figs => no regions.
    if not figure_items:
        return SheetParse(
            page=page_ref,
            render=render,
            regions=tuple(),
            meta={"figures_source": used_source, "figures_count": 0},
        )

    # ---- component extraction (reusing your OpenCV logic) ----
    components: List[Tuple[int, int, int, int]] = []
    header_cut_y = int(0.10 * Hpx)

    if use_opencv and cv2 is not None:
        try:
            import numpy as np

            sheet_rgb = np.array(img)  # HxWx3 RGB
            sheet_bgr = cv2.cvtColor(sheet_rgb, cv2.COLOR_RGB2BGR)

            components = _extract_ink_components(
                cv2=cv2,
                sheet_bgr=sheet_bgr,
                min_area_px=opencv_min_area_px,
                canny1=opencv_canny1,
                canny2=opencv_canny2,
                dilate_iter=opencv_dilate_iter,
                merge_gap_px=opencv_merge_gap_px,
            )
            header_cut_y = _estimate_header_cut_y(components, Wpx, Hpx)
        except Exception as e:
            diag.warn(
                "drawing_segmentation.opencv_components_failed",
                f"OpenCV component extraction failed: {e}",
                field=field,
                meta={"page_index": pdf_page_index},
            )
            components = []

    if use_opencv and cv2 is not None and not components:
        diag.warn(
            "drawing_segmentation.opencv_no_components",
            "OpenCV produced no ink components; will fall back to partition boxes.",
            field=field,
            meta={"page_index": pdf_page_index},
        )

    # ---- partition fallback (same as before) ----
    centers_norm = [_label_center_norm(it.label_bbox_norm) for it in figure_items]
    part_norm = _compute_partition_boxes_norm(centers_norm)
    part_px = [_norm_to_px(b, Wpx, Hpx) for b in part_norm]

    # ---- label geometry precompute (same as before) ----
    label_centers_px: List[Tuple[float, float]] = []
    label_boxes_px: List[Tuple[int, int, int, int]] = []
    for it2 in figure_items:
        lb = _norm_to_px(it2.label_bbox_norm, Wpx, Hpx)
        lb = _expand_box(lb, Wpx, Hpx, label_exclusion_pad_px)
        label_boxes_px.append(lb)
        label_centers_px.append(_centroid(lb))

    # ---- assign components to labels (same as before) ----
    assigned: List[List[Tuple[int, int, int, int]]] = [[] for _ in figure_items]
    if components:
        components2 = [c for c in components if _centroid(c)[1] >= float(header_cut_y)]
        for comp in components2:
            cc = _centroid(comp)
            best_i = None
            best_score = None
            for i in range(len(figure_items)):
                lc = label_centers_px[i]
                score = _sqdist(cc, lc)

                if assign_prefer_above_label and cc[1] > lc[1]:
                    score *= float(assign_below_penalty)

                if _overlaps_label(comp, label_boxes_px[i], min_overlap_frac=0.10):
                    score *= float(assign_label_overlap_penalty)

                if best_score is None or score < best_score:
                    best_score = score
                    best_i = i

            if best_i is not None:
                assigned[best_i].append(comp)

    def crop_from_components(
        comps: List[Tuple[int, int, int, int]],
    ) -> Optional[Tuple[int, int, int, int]]:
        u = _union_boxes(comps)
        if u is None:
            return None
        return _expand_box(u, Wpx, Hpx, opencv_crop_margin_px)

    # ---- build regions (bbox only; no export) ----
    sheet_area = float(Wpx * Hpx)
    max_r2 = (fallback_radius_frac * float(max(Wpx, Hpx))) ** 2

    regions: List[DrawingRegion] = []

    for idx, it in enumerate(figure_items):
        used_partition = False
        used_radius = False

        # Remove caption-overlapping components
        base_comps = [
            c
            for c in assigned[idx]
            if not _overlaps_label(c, label_boxes_px[idx], min_overlap_frac=0.10)
        ]
        crop_px = crop_from_components(base_comps)

        # If we got a crop, ensure it doesn't include header
        if crop_px is not None:
            x0, y0, x1, y1 = crop_px
            if y0 < header_cut_y:
                crop_px = (x0, header_cut_y, x1, y1)

        # Radius fallback if crop too small
        if (
            crop_px is not None
            and (_area(crop_px) / sheet_area) < float(min_crop_area_frac)
            and components
        ):
            lc = label_centers_px[idx]
            expanded: List[Tuple[int, int, int, int]] = []
            for c in components:
                if _overlaps_label(c, label_boxes_px[idx], min_overlap_frac=0.10):
                    continue
                cc = _centroid(c)
                if assign_prefer_above_label and cc[1] > lc[1]:
                    continue
                if _sqdist(cc, lc) <= max_r2:
                    expanded.append(c)

            cand = crop_from_components(expanded)
            if cand is not None and (_area(cand) / sheet_area) >= (
                _area(crop_px) / sheet_area
            ):
                crop_px = cand
                used_radius = True
                diag.info_msg(
                    "drawing_segmentation.radius_fallback_used",
                    "Expanded crop using radius fallback around label center.",
                    field=field,
                    meta={
                        "page_index": pdf_page_index,
                        "figure": _figure_slug(it.figure_number, it.subfigure_id),
                    },
                )

        # Partition fallback if still none
        if crop_px is None:
            crop_px = _expand_box(part_px[idx], Wpx, Hpx, opencv_crop_margin_px)
            used_partition = True
            diag.warn(
                "drawing_segmentation.partition_fallback_used",
                "Used partition fallback (no components assigned to this figure).",
                field=field,
                meta={
                    "page_index": pdf_page_index,
                    "figure": _figure_slug(it.figure_number, it.subfigure_id),
                },
            )

        bbox_norm_list = _px_to_norm(crop_px, Wpx, Hpx)
        bbox_norm = BBoxNorm(*bbox_norm_list)

        fig = FigureLabel(
            raw=it.label,
            slug=_figure_slug(it.figure_number, it.subfigure_id),
            figure_number=it.figure_number,
            subfigure_id=it.subfigure_id,
            confidence=it.confidence,
            source=it.source,
        )

        meta = DrawingRegionMeta(
            region_index=idx,
            method="opencv-cc+label",
            confidence=0.6 if not used_partition else 0.4,
            header_cut_y_px=int(header_cut_y),
            used_partition_fallback=used_partition,
            used_radius_fallback=used_radius,
        )

        regions.append(
            DrawingRegion(
                page=page_ref,
                crop_bbox_norm=bbox_norm,
                fig=fig,
                meta=meta,
            )
        )

    return SheetParse(
        page=page_ref,
        render=render,
        regions=tuple(regions),
        meta={
            "figures_source": used_source,
            "figures_count": len(figure_items),
            "opencv_used": bool(use_opencv and cv2 is not None),
            "header_cut_y_px": int(header_cut_y),
        },
    )
