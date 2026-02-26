from __future__ import annotations

import pymupdf
import json
from pathlib import Path


import pytest


from tests.assertions import (
    assert_analysis_matches_expectations,
    assert_semantic_inids_against_expectation,
)

pytestmark = pytest.mark.integration

# Change these two constants as you iterate PDF-by-PDF
PDF_NAME = "US7629993B2.pdf"
EXP_NAME = "US7629993B2.json"


def test_uspto_7629993B2_analysis(fixtures_dir: Path, expectations_dir: Path):
    from patent_ingest.model.analysis import analyze_document  # adjust if needed

    pdf_path = fixtures_dir / PDF_NAME
    exp_path = expectations_dir / EXP_NAME

    assert pdf_path.exists(), f"Missing fixture PDF: {pdf_path}"
    assert exp_path.exists(), f"Missing expectations JSON: {exp_path}"

    exp = json.loads(exp_path.read_text(encoding="utf-8"))

    doc = pymupdf.open(pdf_path)
    res = analyze_document(doc)

    assert_analysis_matches_expectations(res, exp)


def test_uspto_7629993B2_semantic(fixtures_dir: Path, expectations_dir: Path):
    from patent_ingest.model.analysis import analyze_document  # adjust if needed

    pdf_path = fixtures_dir / PDF_NAME
    exp_path = expectations_dir / EXP_NAME

    assert pdf_path.exists(), f"Missing fixture PDF: {pdf_path}"
    assert exp_path.exists(), f"Missing expectations JSON: {exp_path}"

    exp = json.loads(exp_path.read_text(encoding="utf-8"))

    doc = pymupdf.open(pdf_path)
    res = analyze_document(doc)

    assert_semantic_inids_against_expectation(res, exp)
