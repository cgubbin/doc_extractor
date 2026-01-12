from __future__ import annotations
from pathlib import Path
import shutil
import numpy as np
from PIL import Image
from .config import PipelineConfig
from .models import FigureAsset

def _analyze_page(path: str) -> tuple[float, float]:
    """Return (image_coverage, edge_density)."""
    img = Image.open(path).convert("L")  # grayscale
    arr = np.array(img, dtype=np.uint8)

    # Normalize "whiteness" threshold; patents are mostly white background
    nonwhite = arr < 245
    coverage = float(nonwhite.mean())

    # Simple edge density via gradient magnitude threshold
    # (fast and dependency-light; good enough for drawing pages)
    gx = np.abs(np.diff(arr.astype(np.int16), axis=1))
    gy = np.abs(np.diff(arr.astype(np.int16), axis=0))
    # pad to original shape
    gx = np.pad(gx, ((0,0),(0,1)), mode="constant")
    gy = np.pad(gy, ((0,1),(0,0)), mode="constant")
    grad = gx + gy
    edges = grad > 40
    edge_density = float(edges.mean())
    return coverage, edge_density

def select_figure_pages(rendered_pages: list[str], selected_dir: str, cfg: PipelineConfig) -> list[FigureAsset]:
    """Heuristically select pages likely to be drawings/figures."""
    Path(selected_dir).mkdir(parents=True, exist_ok=True)

    scored: list[tuple[str, float, float, float]] = []
    for p in rendered_pages[: cfg.figure_select_max_pages or len(rendered_pages)]:
        cov, ed = _analyze_page(p)
        # Weighted score: prefer pages with substantial ink and edges (line drawings)
        score = (cov * 0.65) + (ed * 0.35)
        scored.append((p, cov, ed, score))

    # Filter: must pass minimum thresholds
    keep = [
        (p, cov, ed, score) for (p, cov, ed, score) in scored
        if cov >= cfg.figure_select_min_image_coverage and ed >= cfg.figure_select_min_edge_density
    ]

    # If nothing passes, fall back to top-N by score (avoid returning empty)
    if not keep and scored:
        keep = sorted(scored, key=lambda x: x[3], reverse=True)[:4]
    else:
        keep = sorted(keep, key=lambda x: x[3], reverse=True)

    assets: list[FigureAsset] = []
    for p, cov, ed, score in keep:
        src = Path(p)
        # page-0001.jpg style names come from pdftoppm; keep stable naming
        dest = Path(selected_dir) / f"figure_{src.name}"
        shutil.copyfile(src, dest)
        page_no = _page_no_from_name(src.name)
        assets.append(FigureAsset(path=str(dest), source="rendered", page=page_no, score=score,
                                  note=f"coverage={cov:.3f}, edge_density={ed:.3f}"))
    return assets

def _page_no_from_name(name: str) -> int | None:
    # pdftoppm names like page-1.jpg OR page-0001.jpg depending on version; handle both.
    import re
    m = re.search(r"page-(\d+)", name)
    return int(m.group(1)) if m else None
