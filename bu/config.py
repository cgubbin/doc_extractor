from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineConfig:
    # Tooling
    pdftotext_path: str = "pdftotext"
    pdfimages_path: str = "pdfimages"
    pdftoppm_path: str = "pdftoppm"

    # Text extraction
    pdftotext_layout: bool = True  # -layout helps claim numbering
    pdftotext_raw: bool = True  # -raw sometimes preserves spacing; can toggle
    pdftotext_encoding: str = "UTF-8"  # -enc
    max_pages_for_render: int | None = None  # optionally limit page renders

    # Figures
    figure_mode: str = "auto"  # "auto" | "embedded" | "render"
    render_dpi: int = 200  # for pdftoppm
    jpg_quality: int = 85  # if you later re-encode via pillow

    # Claims parsing
    min_claims_expected: int = 1

    # Alignment / diff
    match_threshold: float = 0.72
    unchanged_threshold: float = 0.96

    # Excerpts
    excerpt_window_chars: int = 600
    max_excerpts_per_section: int = 25
