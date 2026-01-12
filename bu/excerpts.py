from __future__ import annotations
import re
from models import RelevantExcerpt, ClaimsDiffResult


def extract_relevant_excerpts(
    normalized_text: str,
    section_spans: dict,
    claims_diff: ClaimsDiffResult,
    source_label: str,
    window_chars: int,
    max_per_section: int,
) -> list[RelevantExcerpt]:
    """
    V1: pull excerpts around changed-term anchors found in diffs, plus include changed claims directly.
    """
    excerpts: list[RelevantExcerpt] = []

    # 1) Always include changed claims text as excerpts (section=claims)
    for al in claims_diff.alignments:
        if al.status in ("added", "removed", "modified"):
            if source_label == "submitted" and al.submitted_no is not None:
                text = _claim_text_from_alignment(al, which="submitted")
            elif source_label == "approved" and al.approved_no is not None:
                text = _claim_text_from_alignment(al, which="approved")
            else:
                continue
            excerpts.append(
                RelevantExcerpt(
                    source=source_label,
                    section="claims",
                    start=-1,
                    end=-1,
                    text=text,
                    reason=f"claim_{al.status}",
                    score=10.0,
                )
            )

    # 2) Anchor phrases from diffs (insertions + replacements 'to')
    anchors = _extract_anchors(claims_diff)
    if not anchors:
        return _dedupe(excerpts)[:max_per_section]

    # Search within non-claims text (e.g., full doc). If you want, constrain to description span.
    search_space = normalized_text
    for phrase in anchors:
        for m in re.finditer(re.escape(phrase), search_space, flags=re.IGNORECASE):
            s = max(0, m.start() - window_chars)
            e = min(len(search_space), m.end() + window_chars)
            chunk = search_space[s:e].strip()
            if not chunk:
                continue
            excerpts.append(
                RelevantExcerpt(
                    source=source_label,
                    section="fulltext",
                    start=s,
                    end=e,
                    text=chunk,
                    reason="changed_term_hit",
                    score=5.0,
                )
            )

    return _dedupe(excerpts)[: (max_per_section * 2)]


def _extract_anchors(claims_diff: ClaimsDiffResult) -> list[str]:
    phrases: set[str] = set()
    for al in claims_diff.alignments:
        if al.status not in ("modified", "added"):
            continue
        diff = al.diff or {}
        for ins in diff.get("insertions", []):
            p = _good_anchor(ins)
            if p:
                phrases.add(p)
        for rep in diff.get("replacements", []):
            to = rep.get("to", "")
            p = _good_anchor(to)
            if p:
                phrases.add(p)

    # Keep anchors modest length to avoid huge exact-match misses
    out = sorted(phrases, key=len, reverse=True)
    return out[:30]


def _good_anchor(s: str) -> str | None:
    s = " ".join(s.split()).strip(" ,;:.")
    if len(s) < 12:
        return None
    if len(s) > 80:
        s = s[:80].rsplit(" ", 1)[0]
    return s or None


def _claim_text_from_alignment(al, which: str) -> str:
    # For v1 we store full added/removed in diff; for modified we provide unified diff
    if al.status == "added":
        return al.diff.get("added_full", "")
    if al.status == "removed":
        return al.diff.get("deleted_full", "")
    # modified
    return al.diff.get("unified", "")


def _dedupe(excerpts: list[RelevantExcerpt]) -> list[RelevantExcerpt]:
    seen = set()
    out = []
    for ex in excerpts:
        key = (ex.section, ex.start, ex.end, ex.reason, ex.text[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(ex)
    return out
