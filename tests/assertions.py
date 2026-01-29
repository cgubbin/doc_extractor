from __future__ import annotations

from typing import Any, Dict

from tests.normalise import normalise_for_contains
from tests.token_extractors import (
    extract_ipc_tokens,
    extract_uscl_tokens,
    extract_codeish_tokens,
    extract_patent_id_tokens,
    extract_application_id_tokens,
    assert_tokens_present,
)


def assert_inids_against_expectation(res: Any, exp: Dict[str, Any]) -> None:
    """
    res.inid.fields: dict[int, str]
    exp: loaded JSON expectation dict
    Supports:
      - exp["inid_contains"][<tag>] = [phrases...]
      - exp["inid_tokens"][<tag>] = { "ipc": [...], "uscl": [...], "codeish": [...], "fuzzy": {...} }
    """

    # --- existing contains checks (keep as-is) ---
    for k, phrases in exp.get("inid_contains", {}).items():
        print(k, phrases)
        k_int = int(k)
        got = normalise_for_contains(res.inid.fields.get(k_int, ""))
        for ph in phrases:
            want = normalise_for_contains(ph)
            assert want in got, f"INID ({k}) missing phrase: {ph!r}\nGOT={got[:250]!r}"

    # --- new token checks for noisy fields ---
    for k, spec in exp.get("inid_tokens", {}).items():
        print(k, spec)
        k_int = int(k)
        print(res.inid.fields)
        raw = res.inid.fields.get(k_int, "")
        print(raw)
        got_norm = normalise_for_contains(raw)
        print(got_norm)

        # token categories
        if "ipc" in spec:
            got = extract_ipc_tokens(got_norm)
            assert_tokens_present(spec["ipc"], got, label=f"INID({k}) IPC")

        if "uscl" in spec:
            got = extract_uscl_tokens(got_norm)
            assert_tokens_present(spec["uscl"], got, label=f"INID({k}) USCL")

        if "codeish" in spec:
            got = extract_codeish_tokens(got_norm)
            assert_tokens_present(spec["codeish"], got, label=f"INID({k}) CODEISH")

        if "patent_id" in spec:
            got = extract_patent_id_tokens(got_norm)
            assert_tokens_present(
                spec["patent_id"],
                got,
                label=f"INID({k}) PATENT_ID",
            )

        if "app_id" in spec:
            got = extract_application_id_tokens(got_norm)
            assert_tokens_present(
                spec["app_id"],
                got,
                label=f"INID({k}) APP_ID",
            )

        # optional fuzzy section:
        # "fuzzy": { "ipc": {"tokens":[...], "max_dist":2}, "uscl": {...}, ... }
        fuzzy = spec.get("fuzzy", {})
        if "ipc" in fuzzy:
            got = extract_ipc_tokens(got_norm)
            tokens = fuzzy["ipc"]["tokens"]
            max_dist = int(fuzzy["ipc"].get("max_dist", 2))
            assert_tokens_present(
                tokens, got, fuzzy=True, max_dist=max_dist, label=f"INID({k}) IPC"
            )

        if "uscl" in fuzzy:
            got = extract_uscl_tokens(got_norm)
            tokens = fuzzy["uscl"]["tokens"]
            max_dist = int(fuzzy["uscl"].get("max_dist", 1))
            assert_tokens_present(
                tokens, got, fuzzy=True, max_dist=max_dist, label=f"INID({k}) USCL"
            )

        if "codeish" in fuzzy:
            got = extract_codeish_tokens(got_norm)
            tokens = fuzzy["codeish"]["tokens"]
            max_dist = int(fuzzy["codeish"].get("max_dist", 1))
            assert_tokens_present(
                tokens, got, fuzzy=True, max_dist=max_dist, label=f"INID({k}) CODEISH"
            )

        if "patent_id" in fuzzy:
            got = extract_patent_id_tokens(got_norm)
            tokens = fuzzy["patent_id"]["tokens"]
            max_dist = int(fuzzy["patent_id"].get("max_dist", 1))
            assert_tokens_present(
                tokens,
                got,
                fuzzy=True,
                max_dist=max_dist,
                label=f"INID({k}) PATENT_ID",
            )

        if "app_id" in fuzzy:
            got = extract_application_id_tokens(got_norm)
            tokens = fuzzy["app_id"]["tokens"]
            max_dist = int(fuzzy["app_id"].get("max_dist", 1))
            assert_tokens_present(
                tokens,
                got,
                fuzzy=True,
                max_dist=max_dist,
                label=f"INID({k}) APP_ID",
            )


def assert_analysis_matches_expectations(res: Any, exp: Dict[str, Any]) -> None:
    """
    Assert DocumentAnalysis result matches expectation dict.
    Keep checks semantic and robust (phrase containment, counts, indices, etc).
    """

    # --- Drawings ---
    drawings = exp.get("drawings", {})
    if "count" in drawings:
        print(f"Asserting drawings.count {res.drawings.count} =", drawings["count"])
        assert res.drawings.count == drawings["count"]
    if "page_indices" in drawings:
        print(
            f"Asserting drawings.page_indices {res.drawings.page_indices} =",
            drawings["page_indices"],
        )
        assert res.drawings.page_indices == drawings["page_indices"]

    # Optional: tolerate range-based assertions
    drawings_range = exp.get("drawings_range")
    if drawings_range:
        lo = drawings_range.get("min")
        hi = drawings_range.get("max")
        if lo is not None:
            assert all(p >= lo for p in res.drawings.page_indices)
        if hi is not None:
            assert all(p <= hi for p in res.drawings.page_indices)

    # --- INIDs ---
    for k in exp.get("required_inids", []):
        assert int(k) in res.inid.fields, f"Missing INID ({k})"

    assert_inids_against_expectation(res, exp)

    # for k, phrases in exp.get("inid_contains", {}).items():
    #     k_int = int(k)
    #     got = normalise_for_contains(res.inid.fields.get(k_int, ""))
    #     for ph in phrases:
    #         want = normalise_for_contains(ph)
    #         assert want in got, f"INID ({k}) missing phrase: {ph!r}\nGOT={got[:250]!r}"

    # --- Body pages ---
    if "body_pages" in exp:
        print(f"Asserting body.pages {res.body.pages} =", exp["body_pages"])
        assert res.body.pages == exp["body_pages"]

    # --- Headings ---
    min_section_headings = exp.get("min_section_headings")
    if min_section_headings is not None:
        print("Checking min_section_headings:", min_section_headings)
        print(
            "Found headings:",
            [b.text for b in res.body.blocks if b.kind == "section_heading"],
        )
        headings = [b for b in res.body.blocks if b.kind == "section_heading"]
        assert len(headings) >= int(min_section_headings)

    expected_any = exp.get("expected_section_headings_any")
    if expected_any:
        got_set = {
            normalise_for_contains(b.text)
            for b in res.body.blocks
            if b.kind == "section_heading"
        }
        want_set = {normalise_for_contains(s) for s in expected_any}
        assert got_set & want_set, (
            f"No expected section heading found. want={sorted(want_set)} got(sample)={sorted(got_set)[:15]}"
        )
