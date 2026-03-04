from __future__ import annotations
from dataclasses import dataclass, field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import difflib
from typing import Optional, Literal
import re


@dataclass(frozen=True)
class ClaimsPolicy:
    require_start_at_1: bool = True
    max_missing_within_range: int = 3  # warn if >0; error if >threshold


@dataclass
class WarningItem:
    code: str
    message: str


@dataclass
class ClaimAlignment:
    submitted_no: Optional[int]
    approved_no: Optional[int]
    status: Literal["added", "removed", "modified", "unchanged", "renumbered"]
    similarity: float
    diff: dict


@dataclass
class ClaimsDiffResult:
    alignments: list[ClaimAlignment]
    summary: dict
    warnings: list[WarningItem] = field(default_factory=list)


@dataclass
class AlignmentPair:
    i: int
    j: int
    score: float


@dataclass(frozen=True)
class Claim:
    number: int
    text: str
    depends_on: list[int] = field(default_factory=list)
    is_independent: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> Claim:
        return cls(
            number=d.get("number", 0),
            text=d.get("text", ""),
            depends_on=d.get("depends_on", []),
            is_independent=d.get("is_independent", True),
        )


_DEP_SINGLE = re.compile(r"\bclaim\s+(\d+)\b", re.IGNORECASE)
_DEP_RANGE = re.compile(r"\bclaims?\s+(\d+)\s*(?:-|to)\s*(\d+)\b", re.IGNORECASE)
_DEP_LIST = re.compile(r"\bclaims?\s+((?:\d+\s*(?:,|and|or)?\s*)+)\b", re.IGNORECASE)
# quick guard to skip things like "claiming" etc.
_CLAIM_WORD = re.compile(r"\bclaim\b", re.IGNORECASE)


def _extract_depends_on(text: str) -> list[int]:
    """
    Conservative dependency extraction:
    - claim N
    - claims N-M
    - claims N, N, and N
    """
    if not text or not _CLAIM_WORD.search(text):
        return []

    deps: set[int] = set()

    # ranges first
    for a, b in _DEP_RANGE.findall(text):
        lo, hi = int(a), int(b)
        if lo > hi:
            lo, hi = hi, lo
        # cap to avoid runaway if OCR creates huge numbers
        if hi - lo <= 200:
            deps.update(range(lo, hi + 1))

    # list forms
    for m in _DEP_LIST.finditer(text):
        seq = m.group(1)
        for n in re.findall(r"\d+", seq):
            deps.add(int(n))

    # single mentions
    for n in _DEP_SINGLE.findall(text):
        deps.add(int(n))

    return sorted(deps)


_CLAIM_PREFIX = re.compile(r"^\s*(\d+)\s*\.\s*(.*)\s*$", re.DOTALL)


def claims_from_chunks(chunks: list[str]) -> list[Claim]:
    out: list[Claim] = []
    for chunk in chunks:
        m = _CLAIM_PREFIX.match(chunk)
        if not m:
            # skip malformed; caller should diagnose
            continue
        num = int(m.group(1))
        txt = m.group(2).strip()
        deps = _extract_depends_on(txt)
        out.append(Claim(number=num, text=txt, depends_on=deps))
    # sort by claim number (chunks should already be ordered, but don't trust it)
    out.sort(key=lambda c: c.number)
    return out


def validate_claims(claims: list[Claim], diag, *, field: str = "claims") -> None:
    if not claims:
        diag.warn("claims.none", "No claims parsed.", field=field)
        return

    nums = [c.number for c in claims]
    uniq = sorted(set(nums))

    # 1) duplicates
    if len(uniq) != len(nums):
        # find duplicates
        seen = set()
        dups = []
        for n in nums:
            if n in seen:
                dups.append(n)
            else:
                seen.add(n)
        diag.warn(
            "claims.duplicate_numbers",
            f"Duplicate claim numbers parsed: {sorted(set(dups))}",
            field=field,
            meta={"duplicates": sorted(set(dups))},
        )

    # 2) monotonicity / gaps
    # expected range is from min to max (common assumption for patents)
    lo, hi = uniq[0], uniq[-1]
    missing = [n for n in range(lo, hi + 1) if n not in set(uniq)]
    if missing:
        # Heuristic: missing a few within range is likely OCR/segmentation issue
        diag.warn(
            "claims.missing_numbers",
            f"Missing claim numbers within parsed range {lo}-{hi}: {missing}",
            field=field,
            meta={"range": [lo, hi], "missing": missing},
        )

    # 3) dependency sanity
    present = set(uniq)
    for c in claims:
        bad = [d for d in c.depends_on if d not in present and d <= hi + 5]
        if bad:
            diag.warn(
                "claims.depends_on_missing",
                f"Claim {c.number} depends on missing claims: {bad}",
                field=field,
                meta={"claim": c.number, "missing_deps": bad},
            )

    # 4) independent claim heuristic
    # If claim 1 depends on something, it's likely parsing error.
    c1 = next((c for c in claims if c.number == 1), None)
    if c1 and c1.depends_on:
        diag.warn(
            "claims.claim1_has_deps",
            f"Claim 1 appears to depend on claims {c1.depends_on}; likely parse artifact.",
            field=field,
            meta={"depends_on": c1.depends_on},
        )


def align_claims(submitted: list[Claim], approved: list[Claim], match_threshold: float):
    if not submitted or not approved:
        return [], list(range(len(submitted))), list(range(len(approved)))

    sub_texts = [_norm(c.text) for c in submitted]
    app_texts = [_norm(c.text) for c in approved]

    vect = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    X = vect.fit_transform(sub_texts + app_texts)
    Xs = X[: len(sub_texts)]
    Xa = X[len(sub_texts) :]

    sim = cosine_similarity(Xs, Xa)

    cand = []
    for i in range(sim.shape[0]):
        for j in range(sim.shape[1]):
            s = float(sim[i, j])
            if s >= match_threshold:
                cand.append((i, j, s))
    cand.sort(key=lambda x: x[2], reverse=True)

    used_i, used_j = set(), set()
    pairs: list[AlignmentPair] = []
    for i, j, s in cand:
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        pairs.append(AlignmentPair(i=i, j=j, score=s))

    unmatched_sub = [i for i in range(len(submitted)) if i not in used_i]
    unmatched_app = [j for j in range(len(approved)) if j not in used_j]
    return pairs, unmatched_sub, unmatched_app


def _norm(t: str) -> str:
    return " ".join(t.lower().split())


def diff_claims(
    submitted: list[Claim],
    approved: list[Claim],
    pairs,
    un_sub,
    un_app,
    unchanged_threshold: float,
):
    alignments: list[ClaimAlignment] = []

    for p in pairs:
        s = submitted[p.i]
        a = approved[p.j]
        if p.score >= unchanged_threshold:
            status = "unchanged" if s.number == a.number else "renumbered"
        else:
            status = "modified"
        diff_obj = _word_diff(s.text, a.text)
        alignments.append(
            ClaimAlignment(
                submitted_no=s.number,
                approved_no=a.number,
                status=status,
                similarity=p.score,
                diff=diff_obj,
            )
        )

    for i in un_sub:
        s = submitted[i]
        alignments.append(
            ClaimAlignment(
                submitted_no=s.number,
                approved_no=None,
                status="removed",
                similarity=0.0,
                diff={"deleted_full": s.text},
            )
        )

    for j in un_app:
        a = approved[j]
        alignments.append(
            ClaimAlignment(
                submitted_no=None,
                approved_no=a.number,
                status="added",
                similarity=0.0,
                diff={"added_full": a.text},
            )
        )

    def key(al: ClaimAlignment):
        return (
            al.approved_no is None,
            al.approved_no or 10**9,
            al.submitted_no or 10**9,
        )

    alignments.sort(key=key)

    summary = {
        "added": sum(1 for x in alignments if x.status == "added"),
        "removed": sum(1 for x in alignments if x.status == "removed"),
        "modified": sum(1 for x in alignments if x.status == "modified"),
        "unchanged": sum(1 for x in alignments if x.status == "unchanged"),
        "renumbered": sum(1 for x in alignments if x.status == "renumbered"),
        "total_submitted": len(submitted),
        "total_approved": len(approved),
    }

    warnings = []
    if summary["total_submitted"] == 0 or summary["total_approved"] == 0:
        warnings.append(
            WarningItem(
                code="CLAIMS_EMPTY",
                message="One side has zero parsed claims; diff is limited.",
            )
        )

    return ClaimsDiffResult(alignments=alignments, summary=summary, warnings=warnings)


def _word_diff(a: str, b: str) -> dict:
    a_tokens = a.split()
    b_tokens = b.split()
    sm = difflib.SequenceMatcher(a=a_tokens, b=b_tokens)

    inserts, deletes, replaces = [], [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            inserts.append(" ".join(b_tokens[j1:j2]))
        elif tag == "delete":
            deletes.append(" ".join(a_tokens[i1:i2]))
        elif tag == "replace":
            replaces.append(
                {"from": " ".join(a_tokens[i1:i2]), "to": " ".join(b_tokens[j1:j2])}
            )

    unified = "\n".join(
        difflib.unified_diff(
            a.splitlines(),
            b.splitlines(),
            fromfile="submitted",
            tofile="approved",
            lineterm="",
        )
    )
    return {
        "insertions": [x for x in inserts if x.strip()],
        "deletions": [x for x in deletes if x.strip()],
        "replacements": [x for x in replaces if x["from"].strip() or x["to"].strip()],
        "unified": unified,
    }


@dataclass
class RelevantExcerpt:
    source: Literal["submitted", "approved"]
    section: str
    start: int
    end: int
    text: str
    reason: str
    score: float


def extract_relevant_excerpts(
    normalized_text: str,
    claims_diff: ClaimsDiffResult,
    source_label: str,
    window_chars: int,
    max_per_section: int,
):
    excerpts: list[RelevantExcerpt] = []

    # Include changed claim diffs directly
    for al in claims_diff.alignments:
        if al.status in ("added", "removed", "modified"):
            if source_label == "submitted" and al.submitted_no is None:
                continue
            if source_label == "approved" and al.approved_no is None:
                continue
            excerpts.append(
                RelevantExcerpt(
                    source=source_label,
                    section="claims",
                    start=-1,
                    end=-1,
                    text=_claim_text_from_alignment(al),
                    reason=f"claim_{al.status}",
                    score=10.0,
                )
            )

    anchors = _extract_anchors(claims_diff)
    if not anchors:
        return _dedupe(excerpts)[:max_per_section]

    for phrase in anchors:
        for m in re.finditer(re.escape(phrase), normalized_text, flags=re.IGNORECASE):
            s = max(0, m.start() - window_chars)
            e = min(len(normalized_text), m.end() + window_chars)
            chunk = normalized_text[s:e].strip()
            if chunk:
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
        d = al.diff or {}
        for ins in d.get("insertions", []):
            p = _good_anchor(ins)
            if p:
                phrases.add(p)
        for rep in d.get("replacements", []):
            p = _good_anchor(rep.get("to", ""))
            if p:
                phrases.add(p)
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
