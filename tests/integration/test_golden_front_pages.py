import json
import os
import glob
from typing import Any, Dict
from pypdf import PdfReader
import re
from difflib import SequenceMatcher

from patent_ingest.parse_front_page import (
    canonical_front_page,
    extract_page_text,
    parse_front_matter,
)

ROOT = os.path.dirname(os.path.dirname(__file__))
SAMPLES_DIR = os.path.join(ROOT, "..", "corpus", "samples")
GOLD_DIR = os.path.join(ROOT, "..", "corpus", "gold")


def _norm_title(s: str) -> str:
    s = s or ""
    s = s.upper()
    s = re.sub(r"\s+", " ", s).strip()
    # remove punctuation that often varies
    s = re.sub(r"[^A-Z0-9 ]+", "", s)
    return s


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _diff_dicts(expected: Dict[str, Any], got: Dict[str, Any]) -> str:
    """
    Produce a human-readable diff between two flat dicts.
    """
    lines = []

    expected_keys = set(expected.keys())
    got_keys = set(got.keys())

    missing = expected_keys - got_keys
    extra = got_keys - expected_keys
    common = expected_keys & got_keys

    if missing:
        lines.append("Missing keys in output:")
        for k in sorted(missing):
            lines.append(f"  - {k}")

    if extra:
        lines.append("Unexpected extra keys in output:")
        for k in sorted(extra):
            lines.append(f"  + {k}")

    for k in sorted(common):
        ev = expected[k]
        gv = got[k]
        if ev != gv:
            lines.append(f"Mismatch for key '{k}':")
            lines.append(f"  expected: {ev!r}")
            lines.append(f"  got:      {gv!r}")

    return "\n".join(lines)


def test_golden_front_pages_exact_match():
    gold_files = sorted(glob.glob(os.path.join(GOLD_DIR, "*.front.json")))
    assert gold_files, "Add golden files under corpus/gold/*.front.json"

    failures = []

    for gold_path in gold_files:
        with open(gold_path, "r", encoding="utf-8") as f:
            expected = json.load(f)

        base = os.path.splitext(os.path.basename(gold_path))[0]
        patent_id = base.replace(".front", "")
        pdf_path = os.path.join(SAMPLES_DIR, f"{patent_id}.pdf")

        assert os.path.exists(pdf_path), f"Missing sample PDF: {pdf_path}"

        reader = PdfReader(pdf_path)

        N = expected.get("front_matter_pages_to_scan", 3)
        N = min(N, len(reader.pages))
        expected.pop("front_matter_pages_to_scan", None)
        pages_text = [extract_page_text(reader, i, is_front_page=(i == 0)) for i in range(N)]
        parsed = parse_front_matter(pages_text, max_pages=N)

        got = canonical_front_page(parsed)

        title_expected = expected.pop("title", None)
        title_got = got.pop("title", None)

        if title_expected is not None or title_got is not None:
            ne = _norm_title(title_expected)
            ng = _norm_title(title_got)

            # Strict for empty vs non-empty
            if (not ne) != (not ng):
                failures.append("... title empty mismatch ...")
            else:
                score = _similar(ne, ng)
                if score < 0.97:
                    failures.append(
                        f"\n=== GOLDEN MISMATCH: {patent_id} ===\n"
                        f"Title similarity below threshold:\n"
                        f"  expected: {title_expected!r}\n"
                        f"  got:      {title_got!r}\n"
                        f"  normalized_expected: {ne!r}\n"
                        f"  normalized_got:      {ng!r}\n"
                        f"  similarity: {score:.4f} (min 0.9700)\n"
                    )

        if got != expected:
            diff = _diff_dicts(expected, got)
            failures.append(f"\n=== GOLDEN MISMATCH: {patent_id} ===\n{diff}")

    if failures:
        full_msg = f"\n{len(failures)} golden front-page mismatches detected:\n" + "\n".join(
            failures
        )
        raise AssertionError(full_msg)
