"""Shared test fixtures and sample data for unit tests.

This module provides reusable test data and fixtures for testing patent parsing components.
"""

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column, Span, Where, Pos


# ==================== Sample Front Page Data ====================

SAMPLE_FRONT_PAGE_LEFT = """
United States Patent
Smith et al.

Patent No.: US 7,629,993 B2
Date of Patent: Dec. 8, 2009

(54) METHOD AND APPARATUS FOR NETWORK COMMUNICATION

(75) Inventors: John Smith, Seattle, WA (US);
             Jane Doe, Portland, OR (US)

(73) Assignee: Example Corporation, Redmond, WA (US)

(*) Notice: Subject to any disclaimer, the term of this
           patent is extended or adjusted under 35
           U.S.C. 154(b) by 123 days.

(21) Appl. No.: 11/234,567

(22) Filed: Sep. 23, 2005
"""

SAMPLE_FRONT_PAGE_RIGHT = """
(56) References Cited

U.S. PATENT DOCUMENTS

5,123,456 A   6/1992  Johnson
6,789,012 B1  9/2004  Williams et al.
7,234,567 B2  6/2007  Brown

U.S. PATENT APPLICATION PUBLICATIONS

2005/0123456 A1  6/2005  Davis

ABSTRACT

A method and apparatus for network communication is disclosed.
The system includes a network interface for receiving data packets,
a processor for analyzing packet headers, and a memory for storing
routing information. The apparatus improves network throughput by
dynamically adjusting routing tables based on traffic patterns.

20 Claims, 5 Drawing Sheets
"""


# ==================== Sample Claims ====================

SAMPLE_CLAIMS_TEXT = """
CLAIMS

What is claimed is:

1. A method for network communication, comprising:
   receiving a data packet at a network interface;
   analyzing a header of the data packet;
   determining a routing path based on the header; and
   forwarding the data packet along the routing path.

2. The method of claim 1, wherein analyzing the header comprises:
   extracting a destination address from the header; and
   comparing the destination address to entries in a routing table.

3. The method of claim 2, further comprising:
   updating the routing table based on network traffic patterns.

4. The method of claim 1, wherein the data packet is an IP packet.

5. A network device, comprising:
   a network interface configured to receive data packets;
   a processor configured to analyze packet headers; and
   a memory storing routing information.

6. The network device of claim 5, wherein the processor is further
   configured to dynamically update routing tables.
"""


# ==================== Sample Body Sections ====================

SAMPLE_BACKGROUND = """
BACKGROUND

1. Technical Field

The present invention relates to network communication, and more
particularly to methods and apparatuses for routing data packets.

2. Description of Related Art

Traditional network routing systems rely on static routing tables
that are manually configured by network administrators. This approach
has several limitations. First, static routing tables cannot adapt
to changing network conditions. Second, manual configuration is
time-consuming and error-prone.
"""

SAMPLE_SUMMARY = """
SUMMARY

Embodiments of the present invention provide a method and apparatus
for dynamic network routing. The system automatically adjusts routing
tables based on observed traffic patterns, improving network throughput
and reducing latency. The apparatus includes a network interface,
a processor, and memory for storing routing information.
"""

SAMPLE_DETAILED_DESCRIPTION = """
DETAILED DESCRIPTION

FIG. 1 illustrates a network device 100 according to an embodiment
of the present invention. The device 100 includes a network interface
110, a processor 120, and memory 130.

The network interface 110 receives data packets from external sources.
As shown in FIG. 2, each packet includes a header 210 and payload 220.
The header 210 contains routing information such as source and
destination addresses.

Referring to FIG. 3, the processor 120 analyzes the packet header
to determine an appropriate routing path. The routing algorithm
considers multiple factors including network congestion, link quality,
and historical traffic patterns.

FIG. 4 shows a flowchart of the routing method 400. In step 410,
a packet is received. In step 420, the header is analyzed. In step 430,
a routing decision is made. In step 440, the packet is forwarded.

As illustrated in FIGS. 5A-5C, the routing table can be dynamically
updated based on network conditions. FIG. 5A shows the initial state,
FIG. 5B shows an intermediate state after detecting congestion, and
FIG. 5C shows the final optimized state.
"""


# ==================== Sample Drawing Descriptions ====================

SAMPLE_DRAWING_DESCRIPTIONS = """
BRIEF DESCRIPTION OF THE DRAWINGS

FIG. 1 is a block diagram of a network device according to an embodiment.

FIG. 2 illustrates the structure of a data packet.

FIG. 3 is a flowchart of a packet analysis process.

FIG. 4 shows a routing decision algorithm.

FIG. 5A illustrates an initial routing table state.

FIG. 5B shows a routing table during congestion.

FIG. 5C depicts an optimized routing table state.
"""


# ==================== Helper Functions ====================

def create_mock_multipage(left: str, right: str, page_num: int = 0) -> MultiPage:
    """Create a mock MultiPage object for testing.

    Args:
        left: Text for left column
        right: Text for right column
        page_num: Page number (default 0)

    Returns:
        Mock MultiPage object
    """
    from tests.unit.conftest import MultiPageMock, TwoColumnMock

    return MultiPageMock(pages=[TwoColumnMock(left=left, right=right)])


def create_span(text: str, page: int = 0, column: Column = Column.LEFT,
                start_offset: int = 0) -> Span:
    """Create a Span pointing to the given text.

    Args:
        text: The text content
        page: Page number
        column: Column (LEFT or RIGHT)
        start_offset: Starting offset in the column

    Returns:
        Span object
    """
    end_offset = start_offset + len(text)
    return Span(
        start=Pos(page=page, column=column, offset=start_offset),
        end=Pos(page=page, column=column, offset=end_offset),
    )


def create_where(*spans: Span) -> Where:
    """Create a Where object from multiple spans.

    Args:
        *spans: Span objects to combine

    Returns:
        Where object
    """
    if len(spans) == 1:
        return spans[0]
    return Where(parts=list(spans))


# ==================== Sample Patent IDs ====================

SAMPLE_PATENT_IDS = [
    "US7629993B2",
    "US9587932B2",
    "US10935501B2",
    "US10937705B2",
    "US11346768B1",
    "US10107621B2",
]


# ==================== Sample Citation Data ====================

SAMPLE_CITATIONS = {
    "us_patents": [
        "5123456",
        "6789012",
        "7234567",
    ],
    "us_publications": [
        "2005/0123456",
        "2006/0234567",
    ],
}


# ==================== Sample Dates ====================

SAMPLE_DATES = {
    "grant_date": "Dec. 8, 2009",
    "grant_date_iso": "2009-12-08",
    "filed_date": "Sep. 23, 2005",
    "filed_date_iso": "2005-09-23",
}


# ==================== Sample INID Codes ====================

SAMPLE_INID_BLOCKS = {
    "patent_number": "(12) United States Patent\n     Patent No.: US 7,629,993 B2",
    "title": "(54) METHOD AND APPARATUS FOR NETWORK COMMUNICATION",
    "inventors": "(75) Inventors: John Smith, Seattle, WA (US);\n             Jane Doe, Portland, OR (US)",
    "assignee": "(73) Assignee: Example Corporation, Redmond, WA (US)",
    "appl_no": "(21) Appl. No.: 11/234,567",
    "filed_date": "(22) Filed: Sep. 23, 2005",
    "grant_date": "     Date of Patent: Dec. 8, 2009",
}
