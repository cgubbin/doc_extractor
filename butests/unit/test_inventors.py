from patent_ingest.front_matter.inventor import extract_inventors
from patent_ingest.front_matter.inid import parse_inid_blocks_raw

from conftest import mp


def test_inventors_split_and_normalize(diag, linconf):
    doc = mp(
        ("(72) Inventors: Jane Doe (US); John Smith (US)", ""),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_inventors(doc, inids, diag, **linconf)
    assert len(out) == 2
    assert out[0].value.name is not None
    assert out[0].meta["role"] == "inventor"


def test_inventors_spillover_truncated(diag, linconf):
    doc = mp(
        (
            "(72) Inventors: Willard Charles Raymond, Plymouth, MN (US) (73) Assignee: Rudolph Technologies",
            "",
        ),
    )
    inids = parse_inid_blocks_raw(doc, **linconf)
    out = extract_inventors(doc, inids, diag, **linconf)
    # Should not include assignee junk in inventor name(s)
    assert out
    joined = " ".join([i.value.name or "" for i in out])
    assert "Assignee" not in joined
