from __future__ import annotations
import re
from .models import Claim

# Works with merged two-column text, e.g., "... 13.The ... 16.The ..."
# while excluding "claim 12." references.
CLAIM_ANY_RE = re.compile(r"(?i)(?<!claim\s)(?<!claims\s)\b(\d{1,3})\.(?=\s*[A-Z])")

DEPENDENCY_RE = re.compile(
    r"\bclaim(?:s)?\s+(\d+)(?:\s*[-–]\s*(\d+))?",
    re.IGNORECASE
)

def parse_claims(claims_text: str) -> list[Claim]:
    matches = list(CLAIM_ANY_RE.finditer(claims_text))
    if not matches:
        return []

    claims: list[Claim] = []
    for i, m in enumerate(matches):
        no = int(m.group(1))
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(claims_text)
        body = claims_text[m.end():end].strip()
        body = _clean(body)

        deps = _extract_dependencies(body)
        is_ind = len(deps) == 0
        claims.append(Claim(number=no, text=body, depends_on=deps, is_independent=is_ind))

    # Deduplicate if merged text causes accidental repeats
    out = []
    seen = set()
    for c in claims:
        if c.number in seen:
            continue
        seen.add(c.number)
        out.append(c)
    return out

def _clean(t: str) -> str:
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def _extract_dependencies(claim_body: str) -> list[int]:
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
