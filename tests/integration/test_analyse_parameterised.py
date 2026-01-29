# tests/integration/test_pdfs_parametrized.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
import pymupdf

from tests.helpers import norm

pytestmark = pytest.mark.integration


def _iter_cases(fixtures_dir: Path, expectations_dir: Path):
    """
    Pair PDFs with JSON expectations by filename stem.
    e.g. US20110054659A1.pdf -> US20110054659A1.json
    """
    for pdf in sorted(fixtures_dir.glob("*.pdf")):
        exp = expectations_dir / (pdf.stem + ".json")
        if exp.exists():
            yield pdf, exp


@pytest.mark.parametrize("pdf_path,exp_path", [], ids=[])
def test_placeholder(pdf_path, exp_path):
    # this placeholder is replaced dynamically below
    ...


def pytest_generate_tests(metafunc):
    if "pdf_path" in metafunc.fixturenames and "exp_path" in metafunc.fixturenames:
        fixtures_dir = Path(__file__).resolve().parents[1] / "fixtures" / "pdfs"
        expectations_dir = (
            Path(__file__).resolve().parents[1] / "fixtures" / "expectations"
        )
        cases = list(_iter_cases(fixtures_dir, expectations_dir))
        ids = [p.stem for p, _ in cases]
        metafunc.parametrize("pdf_path,exp_path", cases, ids=ids)


def test_pdf_against_expectations(pdf_path: Path, exp_path: Path):
    # Adjust import path to your actual external entry point
    from patent_ingest.public_api import analyze_document

    exp = json.loads(exp_path.read_text(encoding="utf-8"))
    doc = pymupdf.open(pdf_path)
    res = analyze_document(doc)

    # drawings
    if "drawings" in exp:
        if "count" in exp["drawings"]:
            assert res.drawings.count == exp["drawings"]["count"]
        if "page_indices" in exp["drawings"]:
            assert res.drawings.page_indices == exp["drawings"]["page_indices"]

    # body pages
    if "body_pages" in exp:
        assert res.body.pages == exp["body_pages"]

    # required INIDs
    for k in exp.get("required_inids", []):
        assert int(k) in res.inid.fields, f"Missing INID ({k})"

    # INID contains checks
    for k, phrases in exp.get("inid_contains", {}).items():
        k_int = int(k)
        text = norm(res.inid.fields.get(k_int, ""))
        up = text.upper()
        for ph in phrases:
            assert ph.upper() in up, f"INID ({k}) missing phrase: {ph}"

    # section headings
    headings = [b for b in res.body.blocks if b.kind == "section_heading"]
    assert len(headings) >= exp.get("min_section_headings", 0)

    expected_any = [h.upper() for h in exp.get("expected_section_headings_any", [])]
    if expected_any:
        got = {norm(h.text).upper() for h in headings}
        assert any(e in got for e in expected_any), (
            f"No expected heading found. got={sorted(got)[:10]}"
        )
