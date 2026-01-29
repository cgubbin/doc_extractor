from patent_ingest.front_matter.inid import parse_inid_blocks_raw
from patent_ingest.parsed import INIDKind

from conftest import mp


def test_parse_inid_blocks_single_page_two_columns(diag, linconf):
    doc = mp(
        (
            "(21) Appl. No.: 13/766,598\n(22) Filed: Sep. 30, 2002",
            "(45) Date of Patent: Dec. 8, 2009\n(73) Assignee: ACME (US)",
        )
    )
    blocks = parse_inid_blocks_raw(doc, **linconf)
    assert blocks[INIDKind._21].text.strip().startswith("Appl. No.")
    assert blocks[INIDKind._22].text.strip().startswith("Filed:")
    assert blocks[INIDKind._45].text.strip().startswith("Date of Patent")
    assert blocks[INIDKind._73].text.strip().startswith("Assignee")


def test_parse_inid_blocks_across_pages(diag, linconf):
    doc = mp(
        (
            "(73) Assignee: ACME Corporation, New York, NY (US)",
            "(72) Inventors: Jane Doe; John Smith",
        ),
        ("(21) Appl. No.: 10/262,173", "(22) Filed: Sep. 30, 2002"),
    )
    blocks = parse_inid_blocks_raw(doc, **linconf)
    assert INIDKind._73 in blocks
    assert INIDKind._21 in blocks
