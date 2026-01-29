import os

from patent_ingest.model.document import read_pdf_to_multipage
from patent_ingest.front_matter.model import parse_front_matter


ROOT = os.path.dirname(os.path.dirname(__file__))
SAMPLE = os.path.join(ROOT, "..", "corpus", "samples", "US7629993B2.pdf")


def test_single_front_page_extracts_core_fields():
    text = read_pdf_to_multipage(SAMPLE, page_range=range(0, 5))

    parsed = parse_front_matter(text).data

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
