from __future__ import annotations
from pathlib import Path
import glob
from config import PipelineConfig
from utils_subprocess import run_cmd, require_ok
from models import FigureAsset


def extract_figures_embedded(
    pdf_path: str, figures_dir: str, cfg: PipelineConfig
) -> tuple[list[FigureAsset], dict]:
    """
    Uses pdfimages to extract embedded raster images.
    Produces various formats (ppm, png, jpg, etc.) depending on PDF content.
    We then normalize to .jpg by copying through if already jpg/jpeg, else keep as-is for now.
    """
    out = Path(figures_dir)
    out.mkdir(parents=True, exist_ok=True)

    prefix = str(out / "img")
    # -all extracts all images; output format depends on embedded stream filters.
    res = run_cmd([cfg.pdfimages_path, "-all", pdf_path, prefix])
    require_ok(res, "pdfimages")

    # Collect whatever pdfimages produced.
    produced = []
    for ext in (
        "jpg",
        "jpeg",
        "png",
        "ppm",
        "pbm",
        "pgm",
        "tif",
        "tiff",
        "jbig2",
        "jp2",
    ):
        produced.extend(glob.glob(str(out / f"img-*.{ext}")))

    assets: list[FigureAsset] = []
    for p in sorted(produced):
        # If already jpg/jpeg, keep; otherwise keep original (v1). You can add Pillow conversion later.
        assets.append(FigureAsset(path=p, source="embedded"))

    return assets, {
        "command": res.args,
        "stderr": res.stderr,
        "stdout": res.stdout,
        "returncode": res.returncode,
        "count": len(assets),
    }


def extract_figures_render_pages(
    pdf_path: str, figures_dir: str, cfg: PipelineConfig
) -> tuple[list[FigureAsset], dict]:
    """
    Renders pages to JPEG using pdftoppm. This captures vector drawings too.
    """
    out = Path(figures_dir)
    out.mkdir(parents=True, exist_ok=True)

    prefix = str(out / "page")
    args = [cfg.pdftoppm_path, "-jpeg", "-r", str(cfg.render_dpi), pdf_path, prefix]
    res = run_cmd(args)
    require_ok(res, "pdftoppm")

    produced = sorted(glob.glob(str(out / "page-*.jpg")))
    assets = [FigureAsset(path=p, source="rendered") for p in produced]

    return assets, {
        "command": res.args,
        "stderr": res.stderr,
        "stdout": res.stdout,
        "returncode": res.returncode,
        "count": len(assets),
    }


def extract_figures(
    pdf_path: str, figures_dir: str, cfg: PipelineConfig
) -> tuple[list[FigureAsset], list[dict]]:
    logs: list[dict] = []
    mode = cfg.figure_mode.lower()

    if mode in ("embedded", "auto"):
        try:
            assets, log = extract_figures_embedded(pdf_path, figures_dir, cfg)
            logs.append(log)
            # Heuristic: if embedded extraction yields very little, also render pages in auto mode
            if mode == "auto" and len(assets) < 2:
                render_assets, rlog = extract_figures_render_pages(
                    pdf_path, figures_dir, cfg
                )
                logs.append(rlog)
                assets.extend(render_assets)
            return assets, logs
        except Exception as e:
            if mode == "embedded":
                raise
            # fall back to render
            render_assets, rlog = extract_figures_render_pages(
                pdf_path, figures_dir, cfg
            )
            logs.append({"fallback_from": "embedded", "error": str(e)})
            logs.append(rlog)
            return render_assets, logs

    if mode == "render":
        assets, log = extract_figures_render_pages(pdf_path, figures_dir, cfg)
        logs.append(log)
        return assets, logs

    raise ValueError(f"Unknown figure_mode: {cfg.figure_mode}")
