from __future__ import annotations
import re
from models import Claim

CLAIM_START_RE = re.compile(r"(?m)^\s*(\d+)\.\s+(?=\S)")

DEPENDENCY_RE = re.compile(r"\bclaim(?:s)?\s+(\d+)(?:\s*[-–]\s*(\d+))?", re.IGNORECASE)


def parse_claims(claims_text: str) -> list[Claim]:
    """
    Parses numbered claims using a conservative regex.
    """
    matches = list(CLAIM_START_RE.finditer(claims_text))
    if not matches:
        return []

    claims: list[Claim] = []
    for i, m in enumerate(matches):
        no = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(claims_text)
        body = claims_text[m.end() : end].strip()

        depends = _extract_dependencies(body)
        is_ind = len(depends) == 0
        claims.append(
            Claim(
                number=no,
                text=_clean_claim_text(body),
                depends_on=depends,
                is_independent=is_ind,
            )
        )

    return claims


def _clean_claim_text(t: str) -> str:
    # Keep fairly light cleanup; claims often rely on punctuation
    t = re.sub(r"\s+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _extract_dependencies(claim_body: str) -> list[int]:
    """
    Extracts referenced claim numbers, e.g. "The method of claim 1" or "claims 1-3".
    Best-effort and may include false positives; downstream can tolerate.
    """
    deps: set[int] = set()
    for m in DEPENDENCY_RE.finditer(claim_body):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else None
        if b is None:
            deps.add(a)
        else:
            lo, hi = min(a, b), max(a, b)
            for x in range(lo, hi + 1):
                deps.add(x)
    return sorted(deps)
