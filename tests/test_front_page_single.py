import os
from pypdf import PdfReader

from patent_ingest.parse_front_page import extract_page0_text, parse_front_page


ROOT = os.path.dirname(os.path.dirname(__file__))
SAMPLE = os.path.join(ROOT, "corpus", "samples", "US7629993B2.pdf")


def test_single_front_page_extracts_core_fields():
    reader = PdfReader(SAMPLE)
    text0 = extract_page0_text(reader)
    parsed = parse_front_page(text0)

    assert parsed["patent_number"]["normalized"] is not None
    assert parsed["title"]["value"] is not None
    assert len(parsed["title"]["value"]) > 10

    assert parsed["abstract"]["value"] is not None
    assert len(parsed["abstract"]["value"]) > 20

    assert parsed["assignee"]["value"] is not None
    assert len(parsed["inventors"]["parsed"]) >= 1

    # Regression target: references should be found
    assert len(parsed["references_cited"]["cited_us_patents"]) >= 1

    # No critical failures
    assert "missing_title" not in parsed["qa"]["warnings"]
