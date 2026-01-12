from __future__ import annotations
import difflib
from models import Claim, ClaimAlignment, ClaimsDiffResult, WarningItem


def diff_claims(
    submitted: list[Claim],
    approved: list[Claim],
    pairs,
    unmatched_sub_idx: list[int],
    unmatched_app_idx: list[int],
    unchanged_threshold: float,
) -> ClaimsDiffResult:
    alignments: list[ClaimAlignment] = []

    # Matched
    for p in pairs:
        s = submitted[p.i]
        a = approved[p.j]
        if p.score >= unchanged_threshold:
            status = "unchanged" if s.number == a.number else "renumbered"
        else:
            status = "modified" if s.number == a.number else "modified"

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

    # Removed
    for i in unmatched_sub_idx:
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

    # Added
    for j in unmatched_app_idx:
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

    # Sort for readability: approved first then submitted
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

    warnings: list[WarningItem] = []
    if summary["total_submitted"] == 0 or summary["total_approved"] == 0:
        warnings.append(
            WarningItem(
                code="CLAIMS_EMPTY",
                message="One side has zero parsed claims; diff quality is limited.",
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
                {
                    "from": " ".join(a_tokens[i1:i2]),
                    "to": " ".join(b_tokens[j1:j2]),
                }
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
