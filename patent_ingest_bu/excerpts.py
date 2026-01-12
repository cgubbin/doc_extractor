from __future__ import annotations
import re
from .models import RelevantExcerpt, ClaimsDiffResult

def extract_relevant_excerpts(normalized_text: str, claims_diff: ClaimsDiffResult, source_label: str, window_chars: int, max_per_section: int):
    excerpts: list[RelevantExcerpt] = []

    # Include changed claim diffs directly
    for al in claims_diff.alignments:
        if al.status in ("added", "removed", "modified"):
            if source_label == "submitted" and al.submitted_no is None:
                continue
            if source_label == "approved" and al.approved_no is None:
                continue
            excerpts.append(RelevantExcerpt(
                source=source_label,
                section="claims",
                start=-1,
                end=-1,
                text=_claim_text_from_alignment(al),
                reason=f"claim_{al.status}",
                score=10.0,
            ))

    anchors = _extract_anchors(claims_diff)
    if not anchors:
        return _dedupe(excerpts)[:max_per_section]

    for phrase in anchors:
        for m in re.finditer(re.escape(phrase), normalized_text, flags=re.IGNORECASE):
            s = max(0, m.start() - window_chars)
            e = min(len(normalized_text), m.end() + window_chars)
            chunk = normalized_text[s:e].strip()
            if chunk:
                excerpts.append(RelevantExcerpt(
                    source=source_label,
                    section="fulltext",
                    start=s, end=e,
                    text=chunk,
                    reason="changed_term_hit",
                    score=5.0,
                ))

    return _dedupe(excerpts)[: (max_per_section * 2)]

def _extract_anchors(claims_diff: ClaimsDiffResult) -> list[str]:
    phrases: set[str] = set()
    for al in claims_diff.alignments:
        if al.status not in ("modified", "added"):
            continue
        d = al.diff or {}
        for ins in d.get("insertions", []):
            p = _good_anchor(ins)
            if p: phrases.add(p)
        for rep in d.get("replacements", []):
            p = _good_anchor(rep.get("to", ""))
            if p: phrases.add(p)
    out = sorted(phrases, key=len, reverse=True)
    return out[:30]

def _good_anchor(s: str) -> str | None:
    s = " ".join(s.split()).strip(" ,;:.")
    if len(s) < 12:
        return None
    if len(s) > 80:
        s = s[:80].rsplit(" ", 1)[0]
    return s or None

def _claim_text_from_alignment(al) -> str:
    if al.status == "added":
        return al.diff.get("added_full", "")
    if al.status == "removed":
        return al.diff.get("deleted_full", "")
    return al.diff.get("unified", "")

def _dedupe(excerpts):
    seen = set()
    out = []
    for ex in excerpts:
        key = (ex.section, ex.start, ex.end, ex.reason, ex.text[:120])
        if key in seen:
            continue
        seen.add(key)
        out.append(ex)
    return out
