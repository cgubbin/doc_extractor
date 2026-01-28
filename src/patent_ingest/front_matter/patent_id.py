import re
from typing import Optional, Any


from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column, Span, Position
from patent_ingest.parsed import ParsedRaw, EntityKind, ParsedNorm, INIDKind
from patent_ingest.diagnostics import Diagnostics


# Finder/validator: must be raw-string. This one compiles.
US_PATENT_FINDER = re.compile(
    r"""
    (?ix)
    \b
    (?:US\s*)?                  # optional US
    (?:(?:RE|PP|D)\s*)?         # optional prefix
    \d[\d,\s]{5,}\d             # require enough digits to avoid random small numbers
    (?:\s*[A-Z]\d)?             # optional A1/B2 etc (simple)
    \b
    """,
    re.VERBOSE | re.IGNORECASE,
)


def _clean_patent_id_text(s: str) -> str:
    if not s:
        return ""
    s = " ".join(s.split())  # collapse whitespace
    return s.strip()


def _patent_id_valid(s: str) -> bool:
    s = _clean_patent_id_text(s)
    return bool(US_PATENT_FINDER.search(s))


def _patent_id_compact(s: str) -> Optional[str]:
    """
    Very light "uniform form" without trying to fully interpret types:
      "US 10,123,456 B2" -> "US10123456B2"
      "10,123,456"       -> "10123456" (no country if absent)
    If you want always-US, enforce it in here.

    When multiple matches exist, prefer:
      1) Matches starting with "US"
      2) Longer matches (more complete)
    """
    if not s:
        return None
    s = _clean_patent_id_text(s)

    # Find all matches and pick the best one
    matches = list(US_PATENT_FINDER.finditer(s))
    if not matches:
        return None

    # Prefer matches with "US" prefix, then longer matches
    best_match = max(matches, key=lambda m: (
        m.group(0).upper().startswith("US"),  # Prefer "US" prefix
        len(m.group(0)),  # Prefer longer matches
    ))

    token = best_match.group(0)
    token = token.upper().replace(" ", "")
    token = token.replace(",", "")
    return token


def _find_first_patent_id_page0_right(doc: MultiPage) -> Optional[ParsedRaw[str]]:
    """
    Exact heuristic:
      - page 0
      - right column (second column)
      - first match of US_PATENT_FINDER (group 0)
    """
    text = doc.get_column_text(page=0, column=Column.RIGHT)
    m = US_PATENT_FINDER.search(text or "")
    if not m:
        return None
    start, end = m.span(0)
    where = Span(
        start=Position(page=0, column=Column.RIGHT, offset=start),
        end=Position(page=0, column=Column.RIGHT, offset=end),
    )
    return ParsedRaw[str](
        kind=EntityKind.PATENT_ID,
        where=where,
        text=(text[start:end]).strip(),
        confidence=0.35,
        meta={"source": "fallback", "rule": "patent-id:first-match page0/right"},
    )


def extract_patent_id(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    diag: Diagnostics,
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedNorm[str]]:
    """
    Restores the behavior of your previous patent_id extractor while adding Diagnostics:

      1) Prefer INID (when available) *only if format-valid*
      2) Else fallback: first suitable substring in page0/right
         - If fallback match fails validation, still return best-effort (validated=False),
           and emit a WARNING (NOT an error), matching your prior behavior.

    Diagnostics:
      - WARN on INID candidates that are present but invalid
      - ERROR only when *no* candidate is found at all (INID skipped and fallback not found)
      - WARN when fallback exists but fails validation (still returns value)

    Returns ParsedNorm[str] where:
      - value: compacted id if possible, else cleaned
      - meta["human"]: cleaned human token
      - meta["compact"]: compact token (if derived)
      - meta["validated"]: True/False
      - meta["rejections"]: list[dict] (kept for backward compatibility)
    """
    field = "patent_id"
    rejections: list[dict[str, Any]] = []

    # 1) INID candidate(s) — only those present in your enum
    prefer: list[INIDKind] = []
    for name in ("_11", "_10", "_13"):
        if hasattr(INIDKind, name):
            prefer.append(getattr(INIDKind, name))

    for k in prefer:
        raw = inid_blocks.get(k)
        if not raw or not (raw.text or "").strip():
            continue

        clean = _clean_patent_id_text(raw.text)
        if _patent_id_valid(clean):
            compact = _patent_id_compact(clean)
            value = compact or clean

            as_pid = raw.retag(
                EntityKind.PATENT_ID,
                rule="patent-id:from-inid",
                source="inid",
                inid_code=k.value,
            )
            cleaned = ParsedRaw[str](
                kind=as_pid.kind,
                where=as_pid.where,
                text=clean,
                confidence=as_pid.confidence,
                meta={**as_pid.meta, "rejections": rejections},
            )
            return cleaned.normalize_to(
                value=value,
                kind=EntityKind.PATENT_ID,
                system="USPTO",
                rule=f"patent-id:inid{k.value}",
                normalized=bool(compact),
                human=clean,
                compact=compact,
                validated=True,
            )

        # Record rejection (backward-compatible meta) + diagnostics warning
        rej = {
            "source": "inid",
            "inid_code": k.value,
            "reason": "no plausible patent id found in INID text",
            "sample": raw.excerpt(120)
            if hasattr(raw, "excerpt")
            else (raw.text or "")[:120],
        }
        rejections.append(rej)
        diag.warn(
            "patent_id.inid_invalid",
            "INID candidate present but not a valid patent id; skipping.",
            field=field,
            where=raw.where,
            raw=(raw.text or "")[:160],
            inid=k.value,
        )

    # 2) Fallback: page0/right first match
    fb = (
        _find_first_patent_id_page0_right(doc, sep=sep, order=order)
        if _find_first_patent_id_page0_right.__code__.co_argcount >= 3
        else _find_first_patent_id_page0_right(doc)
    )

    if not fb or not (fb.text or "").strip():
        # No fallback; only now is it a hard error
        diag.error(
            "patent_id.missing",
            "No patent id found (no valid INID candidate and no fallback match in page0/right).",
            field=field,
            meta={"rejections": rejections},
        )
        return None

    clean = _clean_patent_id_text(fb.text)
    compact = _patent_id_compact(clean)
    value = compact or clean

    validated = _patent_id_valid(clean)
    if not validated:
        # Preserve prior behavior: return best-effort, but mark validated=False.
        diag.warn(
            "patent_id.fallback_failed_validation",
            "Fallback matched a patent-like token but failed validation; returning best-effort with validated=False.",
            field=field,
            where=fb.where,
            raw=(fb.text or "")[:160],
            meta={"clean": clean, "rejections": rejections},
        )

    return fb.normalize_to(
        value=value,
        kind=EntityKind.PATENT_ID,
        system="USPTO",
        rule="patent-id:fallback page0/right",
        normalized=bool(compact),
        human=clean,
        compact=compact,
        validated=validated,
        rejections=rejections,
        validation_error=None
        if validated
        else "fallback match failed validation (unexpected)",
    )
