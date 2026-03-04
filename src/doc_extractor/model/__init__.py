"""
The model package contains data models and processing functions for the initial pass through a patent pdf.

It attempts to:
1: Segment the document into INID sections from front matter, drawing sheets and the main body text.
2: Associate text with the most likely INID label in the front matter.
3: Extract headings from the main body text.
"""

from doc_extractor.model.model import Line, ColumnStream, PageLayout, Block
from doc_extractor.model.pipeline import (
    build_page_layout,
    segment_page_blocks,
    build_document_inid_dict,
)
