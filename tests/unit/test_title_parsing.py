import pytest

from patent_ingest.parse_front_page import extract_title_between


@pytest.mark.parametrize(
    "front_text, expected",
    [
        # Interleaved (56) right after (54)
        (
            "(54) (56) SAMPLE INSPECTION USING TOPOGRAPHY References Cited U.S. PATENT DOCUMENTS (75) Inventors:",
            "SAMPLE INSPECTION USING TOPOGRAPHY",
        ),
        # Interleaved (56) in the middle; title continues after
        (
            "(54) AUTOMATED WAFER DEFECT INSPECTION (56) References Cited SYSTEMUSING BACKSIDE LLUMINATION (75)",
            "AUTOMATED WAFER DEFECT INSPECTION SYSTEMUSING BACKSIDE LLUMINATION",
        ),
        # Must stop at (71) Applicant
        (
            "(54) SYSTEM FOR DIRECTLY MEASURING DEPTH (71) Applicant: Rudolph Technologies, Inc., Wilmington, MA (US) (72)",
            "SYSTEM FOR DIRECTLY MEASURING DEPTH",
        ),
        # Must stop at table heading even if (71) appears later
        (
            "(54) IMAGE BASED OVERLAY MEASUREMENT WITH FINITE GRATINGS (56) References Cited U.S. PATENT DOCUMENTS (71) Applicant:",
            "IMAGE BASED OVERLAY MEASUREMENT WITH FINITE GRATINGS",
        ),
    ],
)
def test_extract_title_between(front_text, expected):
    got = extract_title_between(front_text)
    assert got and got.get("value") == expected
