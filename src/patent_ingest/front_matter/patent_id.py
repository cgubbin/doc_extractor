import re
from typing import Any, Optional


from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column, Span, Position
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind, EntityKind

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
    Very light “uniform form” without trying to fully interpret types:
      "US 10,123,456 B2" -> "US10123456B2"
      "10,123,456"       -> "10123456" (no country if absent)
    If you want always-US, enforce it in here.
    """
    if not s:
        return None
    s = _clean_patent_id_text(s)

    m = US_PATENT_FINDER.search(s)
    if not m:
        return None

    token = m.group(0)
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
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedNorm[str]]:
    """
    Patent ID extraction, consistent with your new functions:
      1) Prefer INID (when available) *only if format-valid*
      2) Else fallback: first suitable substring in page0/right

    Returns ParsedNorm[str] where:
      - value: compacted id if possible, else cleaned
      - meta["human"]: cleaned human token
      - meta["compact"]: compact token (if derived)
      - meta["validated"]: True/False
      - meta["rejections"]: reasons INID was skipped
    """
    rejections: list[dict[str, Any]] = []

    # 1) INID candidate(s) — add the ones you actually have in your INIDKind enum
    prefer: list[INIDKind] = []
    for name in (
        "_11",
        "_10",
        "_13",
    ):  # common doc-number-ish fields; adjust to your enum set
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

        rejections.append(
            {
                "source": "inid",
                "inid_code": k.value,
                "reason": "no plausible patent id found in INID text",
                "sample": raw.excerpt(120),
            }
        )

    # 2) Fallback: page0/right first match
    fb = _find_first_patent_id_page0_right(doc)
    if not fb or not (fb.text or "").strip():
        return None

    clean = _clean_patent_id_text(fb.text)
    compact = _patent_id_compact(clean)
    value = compact or clean

    # Validate fallback too; if invalid, still return best-effort (like your date fallback #3),
    # but mark validated=False so downstream can decide.
    validated = _patent_id_valid(clean)

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
