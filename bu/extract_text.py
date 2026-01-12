from __future__ import annotations
from pathlib import Path
from config import PipelineConfig
from utils_subprocess import run_cmd, require_ok
from utils_normalize import normalize_text


def extract_text_pdftotext(
    pdf_path: str, raw_txt_path: str, cfg: PipelineConfig
) -> dict:
    Path(raw_txt_path).parent.mkdir(parents=True, exist_ok=True)

    args = [cfg.pdftotext_path]
    if cfg.pdftotext_layout:
        args.append("-layout")
    if cfg.pdftotext_raw:
        args.append("-raw")
    args += ["-enc", cfg.pdftotext_encoding, pdf_path, raw_txt_path]

    res = run_cmd(args)
    require_ok(res, "pdftotext")

    return {
        "command": res.args,
        "stderr": res.stderr,
        "stdout": res.stdout,
        "returncode": res.returncode,
    }


def normalize_text_file(raw_txt_path: str, normalized_txt_path: str) -> None:
    Path(normalized_txt_path).parent.mkdir(parents=True, exist_ok=True)
    raw = Path(raw_txt_path).read_text(encoding="utf-8", errors="replace")
    norm = normalize_text(raw)
    Path(normalized_txt_path).write_text(norm, encoding="utf-8")
