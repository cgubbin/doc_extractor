from patent_ingest.front_matter.model import parse_front_matter
from patent_ingest.parsed import EntityKind
from conftest import mp


def test_front_matter_end_to_end(diag, linconf):
    doc = mp(
        (
            "(10) Patent No.: US 7,629,993 B2\n"
            "(54) Title: A Thing\n"
            "(21) Appl. No.: 10/262,173\n"
            "(22) Filed: Sep. 30, 2002\n"
            "(45) Date of Patent: Dec. 8, 2009\n"
            "(73) Assignee: Rudolph Technologies, Inc., Flanders, NJ (US)\n"
            "(72) Inventors: Willard Charles Raymond, Plymouth, MN (US)\n"
            "(57) ABSTRACT\nA thing.\n12 Claims, 3 Drawing Sheets\n"
            "(56) References Cited\nU.S. PATENT DOCUMENTS\n5,864,394\n",
            "",
        ),
        ("Sheet 1 of 10", ""),
    )
    res = parse_front_matter(doc)

    assert res.data is not None
    fm = res.data
    pid = fm.patent_id
    assert pid is not None
    assert pid.kind == EntityKind.PATENT_ID
    assert pid.meta["validated"] is True
