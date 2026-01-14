from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re

from pypdf import PdfReader, PdfWriter


# ============================================================
# Regex patterns
# ============================================================

_SHEET_OF_RE = re.compile(r"\bSheet\s+([0-9A-Za-z]+)\s+of\s+([0-9]+)\b", re.IGNORECASE)

_FIG_TOKEN_RE = re.compile(r"^(?:Fig\.?|FIG\.?)$", re.IGNORECASE)  # Fig, Fig., FIG, FIG.
_FIG_WORD_RE = re.compile(r"^Fig$", re.IGNORECASE)  # Fig
_FIG_COMBINED_RE = re.compile(r"^(?:Fig\.?|FIG\.?)([0-9]+[A-Za-z]?)$", re.IGNORECASE)  # Fig.3A
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


def _render_page_png(*, pymupdf_doc, pdf_page_index: int, out_path: Path, dpi: int) -> None:
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


def _union_boxes(boxes: List[Tuple[int, int, int, int]]) -> Optional[Tuple[int, int, int, int]]:
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


def _compute_partition_boxes_norm(centers: List[Tuple[float, float]]) -> List[List[float]]:
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


def _estimate_header_cut_y(boxes: List[Tuple[int, int, int, int]], W: int, H: int) -> int:
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
                ex0, ey0, ex1, ey1 = (cx0 - max_gap, cy0 - max_gap, cx1 + max_gap, cy1 + max_gap)
                for j, b in enumerate(boxes):
                    if used[j]:
                        continue
                    bx0, by0, bx1, by1 = b
                    overlaps = not (bx1 < ex0 or bx0 > ex1 or by1 < ey0 or by0 > ey1)
                    if overlaps:
                        cur = (min(cx0, bx0), min(cy0, by0), max(cx1, bx1), max(cy1, by1))
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


def _detect_figures_from_text_words(*, pymupdf_doc, pdf_page_index: int) -> List[_FigureItem]:
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
        lines[(block, line)].append((float(x0), float(y0), float(x1), float(y1), str(txt)))

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
        key=lambda it: (it.figure_number, "" if it.subfigure_id is None else it.subfigure_id)
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
            t for t in tokens if _FIG_TOKEN_RE.fullmatch(t["t"]) or _FIG_WORD_RE.fullmatch(t["t"])
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
            key=lambda it: (it.figure_number, "" if it.subfigure_id is None else it.subfigure_id)
        )
        return items, None

    except Exception as e:
        return [], f"ocr_exception:{type(e).__name__}"


# ============================================================
# Main entry point
# ============================================================


def process_drawing_sheets(
    pdf_path: str,
    *,
    drawing_sheets_expected: int,
    first_drawing_sheet_index: int,
    output_dir: Optional[str] = None,
    export_pdf: bool = True,
    export_png: bool = False,
    png_dpi: int = 200,
    export_figures_png: bool = False,
    figures_png_dirname: str = "figures_png",
    detect_figures: bool = False,
    figure_text_first: bool = True,
    figure_ocr_fallback: bool = True,
    figure_ocr_dpi: int = 200,
    # OpenCV
    use_opencv: bool = True,
    opencv_canny1: int = 50,
    opencv_canny2: int = 150,
    opencv_dilate_iter: int = 2,
    opencv_min_area_px: int = 900,
    opencv_merge_gap_px: int = 12,
    opencv_crop_margin_px: int = 12,
    # Assignment/crop stabilization
    label_exclusion_pad_px: int = 12,
    assign_prefer_above_label: bool = True,
    assign_below_penalty: float = 3.0,
    assign_label_overlap_penalty: float = 5.0,
    min_crop_area_frac: float = 0.02,
    fallback_radius_frac: float = 0.60,
    max_pages_scan: int = 10,
) -> Dict[str, Any]:
    """
    Phase 1 + Phase 2:
      - sheet PDF export
      - sheet PNG export (pymupdf)
      - per-figure PNG export (opencv):
          * extract ink components globally
          * assign components by nearest label (soft penalties for caption ink / below-caption ink)
          * union + margin
          * if crop is tiny, fallback: expand to nearby components within a radius
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

    # Heuristic validation (non-authoritative)
    heuristic_hits = []
    for i in range(start, min(start + max_pages_scan, pdf_num_pages)):
        text = reader.pages[i].extract_text() or ""
        if _SHEET_OF_RE.search(text):
            heuristic_hits.append(i)
    if heuristic_hits and heuristic_hits[:sheet_count] != sheet_page_indices:
        qa_warnings.append(W_HEURISTIC_MISMATCH)
        qa_info["heuristic_sheet_page_indices"] = heuristic_hits

    export_base: Optional[Path] = None
    if output_dir:
        export_base = Path(output_dir)
        if export_pdf:
            (export_base / "sheets").mkdir(parents=True, exist_ok=True)
        if export_png:
            (export_base / "sheets_png").mkdir(parents=True, exist_ok=True)
        if export_figures_png:
            (export_base / figures_png_dirname).mkdir(parents=True, exist_ok=True)

    pymupdf = _try_import_pymupdf()
    if export_png and pymupdf is None:
        qa_warnings.append(W_EXPORT_PNG_NO_RENDERER)

    pymupdf_doc_for_png = pymupdf.open(pdf_path) if (export_png and pymupdf is not None) else None

    if detect_figures and figure_text_first and pymupdf is None:
        qa_warnings.append(W_FIGURES_NO_PYMUPDF)
    pymupdf_doc_for_text = (
        pymupdf.open(pdf_path)
        if (detect_figures and figure_text_first and pymupdf is not None)
        else None
    )

    PILImage = _try_import_pil()
    if export_figures_png and (PILImage is None or not export_png or export_base is None):
        qa_warnings.append(W_EXPORT_FIG_PNG_MISSING_DEPS)
        export_figures_png = False

    cv2 = _try_import_cv2() if (export_figures_png and use_opencv) else None
    if export_figures_png and use_opencv and cv2 is None:
        qa_warnings.append(W_OPENCV_MISSING)
        use_opencv = False

    figures_flat: List[Dict[str, Any]] = []
    figure_count_total: Optional[int] = 0 if detect_figures else None
    sheets: List[Dict[str, Any]] = []

    for sheet_index, pdf_page_index in enumerate(sheet_page_indices):
        page = reader.pages[pdf_page_index]

        # ---------- export sheet PDF ----------
        export_pdf_path: Optional[str] = None
        if export_base and export_pdf:
            try:
                writer = PdfWriter()
                writer.add_page(page)
                p = export_base / "sheets" / f"sheet_{sheet_index + 1:03d}.pdf"
                with open(p, "wb") as f:
                    writer.write(f)
                export_pdf_path = str(p)
            except Exception:
                qa_warnings.append(W_EXPORT_PDF_FAILED)

        # ---------- export sheet PNG ----------
        export_png_path: Optional[str] = None
        if export_base and export_png and pymupdf_doc_for_png is not None:
            try:
                p = export_base / "sheets_png" / f"sheet_{sheet_index + 1:03d}.png"
                _render_page_png(
                    pymupdf_doc=pymupdf_doc_for_png,
                    pdf_page_index=pdf_page_index,
                    out_path=p,
                    dpi=png_dpi,
                )
                export_png_path = str(p)
            except Exception:
                qa_warnings.append(W_EXPORT_PNG_FAILED)

        # ---------- detect figures ----------
        figures_block = {"enabled": bool(detect_figures), "count": None, "items": []}
        figure_items: List[_FigureItem] = []
        used_source: Optional[str] = None

        if detect_figures and figure_text_first and pymupdf_doc_for_text is not None:
            figure_items = _detect_figures_from_text_words(
                pymupdf_doc=pymupdf_doc_for_text, pdf_page_index=pdf_page_index
            )
            if figure_items:
                used_source = "text"
                qa_warnings.append(f"{W_FIGURES_TEXT_USED_PREFIX}{sheet_index}")

        if detect_figures and not figure_items and figure_ocr_fallback:
            items_ocr, err = _detect_figures_from_ocr(
                pdf_path=pdf_path, pdf_page_index=pdf_page_index, dpi=figure_ocr_dpi
            )
            if err == "ocr_stack_unavailable":
                qa_warnings.append(W_FIGURES_OCR_UNAVAILABLE)
            elif err is not None:
                qa_warnings.append(W_FIGURES_OCR_FAILED)
                qa_info.setdefault("figure_ocr_errors", []).append(
                    {"sheet_index": sheet_index, "pdf_page_index": pdf_page_index, "error": err}
                )
            else:
                figure_items = items_ocr
                used_source = "ocr"
                if figure_items:
                    qa_warnings.append(f"{W_FIGURES_OCR_USED_PREFIX}{sheet_index}")

        if detect_figures:
            if figure_count_total is not None:
                figure_count_total += len(figure_items)
            if not figure_items:
                qa_warnings.append(f"{W_FIGURES_NONE_ON_SHEET_PREFIX}{sheet_index}")

        # ---------- per-figure PNG export using OpenCV components + nearest-label assignment ----------
        figure_exports: Dict[Tuple[int, Optional[str]], Optional[str]] = {}
        figure_crop_bboxes_norm: Dict[Tuple[int, Optional[str]], Optional[List[float]]] = {}

        if (
            export_figures_png
            and export_png_path
            and figure_items
            and PILImage is not None
            and export_base is not None
        ):
            try:
                img = PILImage.open(export_png_path)
                Wpx, Hpx = img.size

                components: List[Tuple[int, int, int, int]] = []
                header_cut_y = int(0.10 * Hpx)
                if use_opencv and cv2 is not None:
                    try:
                        sheet_bgr = cv2.imread(export_png_path, cv2.IMREAD_COLOR)
                        if sheet_bgr is not None:
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
                        else:
                            qa_warnings.append(W_OPENCV_COMPONENTS_FAILED)
                    except Exception:
                        qa_warnings.append(W_OPENCV_COMPONENTS_FAILED)

                if use_opencv and cv2 is not None and not components:
                    qa_warnings.append(W_OPENCV_NO_COMPONENTS)

                # Partition (only used as last-resort fallback box)
                centers_norm = [_label_center_norm(it.label_bbox_norm) for it in figure_items]
                part_norm = _compute_partition_boxes_norm(centers_norm)
                part_px = [_norm_to_px(b, Wpx, Hpx) for b in part_norm]

                # Precompute label centers/boxes in pixels for scoring + caption suppression
                label_centers_px: List[Tuple[float, float]] = []
                label_boxes_px: List[Tuple[int, int, int, int]] = []
                for it2 in figure_items:
                    lb = _norm_to_px(it2.label_bbox_norm, Wpx, Hpx)
                    lb = _expand_box(lb, Wpx, Hpx, label_exclusion_pad_px)
                    label_boxes_px.append(lb)
                    label_centers_px.append(_centroid(lb))

                # Assign each component to the best (lowest score) figure
                assigned: List[List[Tuple[int, int, int, int]]] = [[] for _ in figure_items]
                if components:
                    components = [c for c in components if _centroid(c)[1] >= float(header_cut_y)]
                    for comp in components:
                        cc = _centroid(comp)
                        best_i = None
                        best_score = None
                        for i in range(len(figure_items)):
                            lc = label_centers_px[i]
                            score = _sqdist(cc, lc)

                            # Prefer components above caption label (common layout)
                            if assign_prefer_above_label and cc[1] > lc[1]:
                                score *= float(assign_below_penalty)

                            # Penalize components that look like caption ink
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

                # Build per-figure crops
                sheet_area = float(Wpx * Hpx)
                max_r2 = (fallback_radius_frac * float(max(Wpx, Hpx))) ** 2

                for idx, it in enumerate(figure_items):
                    key = (it.figure_number, it.subfigure_id)

                    # Remove caption-overlapping components
                    base_comps = [
                        c
                        for c in assigned[idx]
                        if not _overlaps_label(c, label_boxes_px[idx], min_overlap_frac=0.10)
                    ]
                    crop_px = crop_from_components(base_comps)
                    # Force crops not to include the page header
                    x0, y0, x1, y1 = crop_px
                    if y0 < header_cut_y:
                        crop_px = (x0, header_cut_y, x1, y1)
                    qa_info.setdefault("header_cut_y_by_sheet", []).append(
                        {
                            "sheet_index": sheet_index,
                            "pdf_page_index": pdf_page_index,
                            "header_cut_y": int(header_cut_y),
                        }
                    )

                    # If crop is tiny, expand search radius around label center (fallback)
                    if crop_px is not None and (_area(crop_px) / sheet_area) < float(
                        min_crop_area_frac
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
                            qa_warnings.append(
                                f"{W_OPENCV_FALLBACK_EXPANDED_PREFIX}{_figure_slug(it.figure_number, it.subfigure_id)}"
                            )

                    # If still None, use partition fallback (or if we have no components at all)
                    if crop_px is None:
                        if use_opencv and cv2 is not None and components:
                            qa_warnings.append(
                                f"{W_OPENCV_NO_COMPONENTS_FOR_FIG_PREFIX}{_figure_slug(it.figure_number, it.subfigure_id)}"
                            )
                        crop_px = _expand_box(part_px[idx], Wpx, Hpx, opencv_crop_margin_px)

                    cropped = img.crop(crop_px)
                    slug = _figure_slug(it.figure_number, it.subfigure_id)
                    fname = f"sheet_{sheet_index + 1:03d}_fig_{slug}.png"
                    outp = export_base / figures_png_dirname / fname
                    cropped.save(str(outp))

                    figure_exports[key] = str(outp)
                    figure_crop_bboxes_norm[key] = _px_to_norm(crop_px, Wpx, Hpx)

            except Exception:
                qa_warnings.append(W_EXPORT_FIG_PNG_FAILED)

        # ---------- assemble outputs ----------
        if detect_figures:
            figures_block["items"] = []
            for it in figure_items:
                key = (it.figure_number, it.subfigure_id)
                figures_block["items"].append(
                    {
                        "figure_number": it.figure_number,
                        "subfigure_id": it.subfigure_id,
                        "label": it.label,
                        "label_bbox_norm": it.label_bbox_norm,
                        "confidence": it.confidence,
                        "source": it.source,
                        "export": {"png_path": figure_exports.get(key)},
                        "crop_bbox_norm": figure_crop_bboxes_norm.get(key),
                    }
                )
            figures_block["count"] = len(figure_items)

            for it in figure_items:
                key = (it.figure_number, it.subfigure_id)
                figures_flat.append(
                    {
                        "figure_number": it.figure_number,
                        "subfigure_id": it.subfigure_id,
                        "sheet_index": sheet_index,
                        "pdf_page_index": pdf_page_index,
                        "label_bbox_norm": it.label_bbox_norm,
                        "crop_bbox_norm": figure_crop_bboxes_norm.get(key),
                        "confidence": it.confidence,
                        "source": it.source,
                        "label": it.label,
                        "export": {"png_path": figure_exports.get(key)},
                    }
                )

            qa_info.setdefault("figure_detection_sources", []).append(
                {
                    "sheet_index": sheet_index,
                    "pdf_page_index": pdf_page_index,
                    "source": used_source,
                }
            )

        sheets.append(
            {
                "sheet_index": sheet_index,
                "pdf_page_index": pdf_page_index,
                "export": {"pdf_path": export_pdf_path, "png_path": export_png_path},
                "figures": figures_block,
            }
        )

    figures_flat.sort(key=_stable_figure_sort_key)

    return {
        "drawing_sheets": {
            "expected_sheet_count": drawing_sheets_expected,
            "sheet_count": sheet_count,
            "sheet_page_indices": sheet_page_indices,
            "sheets": sheets,
            "figure_count_total": figure_count_total,
        },
        "figures": figures_flat,
        "qa": {
            "warnings": qa_warnings,
            "info": {
                **qa_info,
                "pdf_num_pages": pdf_num_pages,
                "first_drawing_sheet_index": first_drawing_sheet_index,
                "export_dir": output_dir,
                "export_pdf": export_pdf,
                "export_png": export_png,
                "png_dpi": png_dpi if export_png else None,
                "export_figures_png": export_figures_png,
                "figures_png_dirname": figures_png_dirname if export_figures_png else None,
                "detect_figures": detect_figures,
                "figure_text_first": figure_text_first,
                "figure_ocr_fallback": figure_ocr_fallback,
                "figure_ocr_dpi": figure_ocr_dpi if detect_figures else None,
                "use_opencv": use_opencv,
                "opencv_params": {
                    "canny1": opencv_canny1,
                    "canny2": opencv_canny2,
                    "dilate_iter": opencv_dilate_iter,
                    "min_area_px": opencv_min_area_px,
                    "merge_gap_px": opencv_merge_gap_px,
                    "crop_margin_px": opencv_crop_margin_px,
                }
                if use_opencv
                else None,
                "assignment_params": {
                    "label_exclusion_pad_px": label_exclusion_pad_px,
                    "assign_prefer_above_label": assign_prefer_above_label,
                    "assign_below_penalty": assign_below_penalty,
                    "assign_label_overlap_penalty": assign_label_overlap_penalty,
                    "min_crop_area_frac": min_crop_area_frac,
                    "fallback_radius_frac": fallback_radius_frac,
                },
            },
        },
    }


def canonical_drawing_sheets(result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonicalize drawing-sheets output for golden tests (stable keys only).
    """
    ds = result["drawing_sheets"]
    out = {
        "expected_sheet_count": ds["expected_sheet_count"],
        "sheet_count": ds["sheet_count"],
        "sheet_page_indices": ds["sheet_page_indices"],
    }
    if ds.get("figure_count_total") is not None:
        out["figure_count_total"] = ds["figure_count_total"]
    return out
