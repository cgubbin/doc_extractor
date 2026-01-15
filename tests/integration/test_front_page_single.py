import os
import pymupdf

from patent_ingest.pipeline import _build_front_matter_pages_text


ROOT = os.path.dirname(os.path.dirname(__file__))
SAMPLE = os.path.join(ROOT, "..", "corpus", "samples", "US7629993B2.pdf")


def test_single_front_page_extracts_core_fields():
    doc = pymupdf.open(SAMPLE)
    text = _build_front_matter_pages_text(doc, pages_to_scan=1)

    parsed = text.parse()

    # print(parsed)

    assert parsed.patent_id is not None
    assert parsed.title is not None
    assert parsed.application_number is not None
    assert parsed.filed_date is not None
    assert parsed.grant_date is not None
    assert parsed.assignee is not None
    assert parsed.inventors is not None
    assert parsed.abstract is not None
    assert parsed.reported_counts is not None
    assert parsed.citations is not None

    # No critical failures
    assert "missing_title" not in parsed.qa_warnings
