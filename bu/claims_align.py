from __future__ import annotations
from dataclasses import dataclass
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from models import Claim


@dataclass
class AlignmentPair:
    i: int  # index in submitted
    j: int  # index in approved
    score: float


def align_claims(
    submitted: list[Claim], approved: list[Claim], match_threshold: float
) -> tuple[list[AlignmentPair], list[int], list[int]]:
    """
    TF-IDF cosine similarity alignment, greedy matching.
    Returns matched pairs + unmatched indices for each side.
    """
    if not submitted or not approved:
        return [], list(range(len(submitted))), list(range(len(approved)))

    sub_texts = [_norm(c.text) for c in submitted]
    app_texts = [_norm(c.text) for c in approved]

    vect = TfidfVectorizer(ngram_range=(1, 2), min_df=1)
    X = vect.fit_transform(sub_texts + app_texts)
    Xs = X[: len(sub_texts)]
    Xa = X[len(sub_texts) :]

    sim = cosine_similarity(Xs, Xa)
    # candidate pairs
    cand = []
    for i in range(sim.shape[0]):
        for j in range(sim.shape[1]):
            if sim[i, j] >= match_threshold:
                cand.append((i, j, float(sim[i, j])))

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
