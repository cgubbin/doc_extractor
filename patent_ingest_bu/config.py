from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class PipelineConfig:
    # Poppler binaries
    pdftotext_path: str = "pdftotext"
    pdftoppm_path: str = "pdftoppm"
    pdfinfo_path: str = "pdfinfo"

    # Text extraction
    pdftotext_layout: bool = True
    pdftotext_raw: bool = True
    pdftotext_encoding: str = "UTF-8"

    # Rendering / figures
    render_dpi: int = 220
    figure_select_min_image_coverage: float = 0.18  # fraction of non-white pixels
    figure_select_min_edge_density: float = 0.015   # fraction of edge pixels
    figure_select_max_pages: int | None = None      # None = no cap

    # Claims parsing
    min_claims_expected: int = 1

    # Claim alignment thresholds
    match_threshold: float = 0.72
    unchanged_threshold: float = 0.96

    # Excerpts
    excerpt_window_chars: int = 600
    max_excerpts_per_section: int = 25
