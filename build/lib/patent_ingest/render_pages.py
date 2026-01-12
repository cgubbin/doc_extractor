from __future__ import annotations
from pathlib import Path
import glob
from .config import PipelineConfig
from .utils_subprocess import run_cmd, require_ok

def render_pages_to_jpg(pdf_path: str, pages_dir: str, cfg: PipelineConfig) -> tuple[list[str], dict]:
    out = Path(pages_dir)
    out.mkdir(parents=True, exist_ok=True)
    prefix = str(out / "page")
    args = [cfg.pdftoppm_path, "-jpeg", "-r", str(cfg.render_dpi), pdf_path, prefix]
    res = run_cmd(args)
    require_ok(res, "pdftoppm")
    produced = sorted(glob.glob(str(out / "page-*.jpg")))
    return produced, {"command": res.args, "stderr": res.stderr, "stdout": res.stdout, "returncode": res.returncode, "count": len(produced)}
