import json
import os
from pathlib import Path

from patent_ingest.drawing_sheets import (
    process_drawing_sheets,
    canonical_drawing_sheets,
)


ROOT = os.path.dirname(os.path.dirname(__file__))
CORPUS_DIR = os.path.join(ROOT, "..", "corpus")
CORPUS_DIR = Path("corpus")
SAMPLE_DIR = CORPUS_DIR / "samples"
GOLDEN_DIR = CORPUS_DIR / "gold"


def load_front_matter():
    """
    Minimal stub matching the integration assumptions.
    In the real pipeline this comes from parse_front_matter(...).
    """
    return {
        "reported_counts": {
            "reported_drawing_sheet_count": 6,
        }
    }


def test_golden_drawing_sheet_metadata():
    pdf_path = SAMPLE_DIR / "US9587932B2.pdf"
    expected_path = GOLDEN_DIR / "US9587932B2.drawings.json"

    result = process_drawing_sheets(
        str(pdf_path),
        drawing_sheets_expected=6,
        first_drawing_sheet_index=2,
        export_pdf=False,
    )

    canonical = canonical_drawing_sheets(result)

    with open(expected_path, "r", encoding="utf-8") as f:
        expected = json.load(f)

    assert canonical == expected


def test_export_smoke(tmp_path):
    pdf_path = SAMPLE_DIR / "US9587932B2.pdf"

    out_dir = tmp_path / "exports"

    process_drawing_sheets(
        str(pdf_path),
        drawing_sheets_expected=6,
        first_drawing_sheet_index=2,
        output_dir=str(out_dir),
        export_pdf=True,
    )

    sheets_dir = out_dir / "sheets"
    pdfs = sorted(p.name for p in sheets_dir.glob("sheet_*.pdf"))

    assert pdfs == [
        "sheet_001.pdf",
        "sheet_002.pdf",
        "sheet_003.pdf",
        "sheet_004.pdf",
        "sheet_005.pdf",
        "sheet_006.pdf",
    ]


def test_figure_detection_smoke():
    pdf_path = SAMPLE_DIR / "US9587932B2.pdf"

    result = process_drawing_sheets(
        str(pdf_path),
        drawing_sheets_expected=6,
        first_drawing_sheet_index=2,
        detect_figures=True,
    )

    assert result["drawing_sheets"]["figure_count_total"] == 7
