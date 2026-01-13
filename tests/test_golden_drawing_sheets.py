import json
from pathlib import Path

from patent_ingest.drawing_sheets import (
    process_drawing_sheets,
    canonical_drawing_sheets,
)


CORPUS_DIR = Path("corpus")
EXPECTED_DIR = CORPUS_DIR / "expected"


def load_front_matter_stub():
    """
    Minimal stub matching the integration assumptions.
    In the real pipeline this comes from parse_front_matter(...).
    """
    return {
        "front_page_index": 0,
        # US9587932B2 has a cover page + an extra bibliographic page
        "front_matter_pages_scanned": 2,
        "drawing_sheets_expected": 6,
    }


def test_golden_drawing_sheet_metadata():
    pdf_path = CORPUS_DIR / "US9587932B2.pdf"
    expected_path = EXPECTED_DIR / "US9587932B2.drawings.json"

    front_matter = load_front_matter_stub()

    result = process_drawing_sheets(
        str(pdf_path),
        front_matter=front_matter,
        output_dir=None,
        export_pdf=False,
        export_png=False,
        segment_drawings=False,
    )

    canonical = canonical_drawing_sheets(result)

    with open(expected_path, "r", encoding="utf-8") as f:
        expected = json.load(f)

    assert canonical == expected


def test_export_smoke(tmp_path):
    pdf_path = CORPUS_DIR / "US9587932B2.pdf"
    front_matter = load_front_matter_stub()

    out_dir = tmp_path / "exports"

    result = process_drawing_sheets(
        str(pdf_path),
        front_matter=front_matter,
        output_dir=str(out_dir),
        export_pdf=True,
        export_png=False,
    )

    sheets_dir = out_dir / "sheets"
    assert sheets_dir.exists()

    pdfs = sorted(p.name for p in sheets_dir.glob("sheet_*.pdf"))
    assert pdfs == [
        "sheet_001.pdf",
        "sheet_002.pdf",
        "sheet_003.pdf",
        "sheet_004.pdf",
        "sheet_005.pdf",
        "sheet_006.pdf",
    ]
