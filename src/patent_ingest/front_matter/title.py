import re
from typing import Any, Optional

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind, EntityKind
from patent_ingest.front_matter.util import (
    _linear_find_group1_as_raw,
    normalize_punctuation_spacing,
)

# Capture "(54) ... (next INID marker)" as group(1)
TITLE_INID_FALLBACK_PAT = re.compile(
    r"""
    (?sx)
    \(\s*54\s*\)           # INID marker (54)
    \s*
    (.*?)                  # title payload
    (?=                    # stop before next INID marker or end
       \(\s*\d{2}\s*\)
       | \Z
    )
    """,
    re.VERBOSE | re.DOTALL,
)

TITLE_LABEL_FALLBACK_PAT = re.compile(
    r"(?ix)\bTitle\s*:\s*(.+)$",
    re.MULTILINE,
)

# Headings that commonly follow title/abstract blocks and can contaminate
TITLE_STOP_PAT = re.compile(
    r"\b(ABSTRACT|OTHER\s+PUBLICATIONS|U\.S\.\s*PATENT\s*DOCUMENTS|FOREIGN\s+PATENT\s*DOCUMENTS|"
    r"REFERENCES\s+CITED)\b",
    re.IGNORECASE,
)


def _clean_title_text(s: str) -> str:
    if not s:
        return ""
    # Basic normalization without being too aggressive
    s = s.strip()
    # Cut at common headings if they accidentally get included
    m = TITLE_STOP_PAT.search(s)
    if m:
        s = s[: m.start()].strip()
    # Collapse excessive whitespace/newlines
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s).strip()
    s = normalize_punctuation_spacing(s)
    return s


def _title_valid(s: str) -> bool:
    """
    Minimal validity check: non-empty and not obviously a heading-only artifact.
    """
    if not s:
        return False
    # too short is suspicious (but allow short titles)
    if len(s.strip()) < 3:
        return False
    # reject if it looks like it's just another INID marker or boilerplate
    if re.fullmatch(r"\(\s*\d{2}\s*\)", s.strip()):
        return False
    return True


def extract_title(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
) -> Optional[ParsedNorm[str]]:
    """
    Title extraction, consistent with the date extractors:
      1) INID(54) if present and usable
      2) fallback: regex capture of "(54) ... next INID" in linearized text
      3) fallback: "Title:" label line

    Returns ParsedNorm[str] with:
      - value: cleaned title
      - meta: {source, rule, normalized=True (always), rejections=[...]}
    """
    rejections: list[dict[str, Any]] = []

    # 1) INID(54)
    inid54 = inid_blocks.get(INIDKind._54) if hasattr(INIDKind, "_54") else None
    if inid54 and (inid54.text or "").strip():
        clean = _clean_title_text(inid54.text)
        if _title_valid(clean):
            as_title = inid54.retag(
                EntityKind.TITLE,
                rule="title:from-inid54",
                source="inid",
                inid_code="54",
            )
            cleaned = ParsedRaw[str](
                kind=as_title.kind,
                where=as_title.where,
                text=clean,
                confidence=as_title.confidence,
                meta={**as_title.meta, "rejections": rejections},
            )
            return cleaned.normalize_to(
                value=clean,
                kind=EntityKind.TITLE,
                system="PDF",
                rule="title:inid54",
                normalized=True,
            )
        rejections.append(
            {
                "source": "inid",
                "inid_code": "54",
                "reason": "title invalid/empty after cleaning",
                "sample": inid54.excerpt(120),
            }
        )

    # 2) fallback: "(54) ... next INID"
    fb1 = _linear_find_group1_as_raw(
        doc,
        TITLE_INID_FALLBACK_PAT,
        kind=EntityKind.TITLE,
        sep=sep,
        order=order,
        confidence=0.35,
        meta={"rule": "title:fallback (54) block", "rejections": rejections},
    )
    if fb1 and (fb1.text or "").strip():
        clean = _clean_title_text(fb1.text)
        if _title_valid(clean):
            cleaned = ParsedRaw[str](
                kind=fb1.kind,
                where=fb1.where,
                text=clean,
                confidence=fb1.confidence,
                meta={**fb1.meta, "rejections": rejections},
            )
            return cleaned.normalize_to(
                value=clean,
                kind=EntityKind.TITLE,
                system="PDF",
                rule="title:fallback-inid-marker",
                normalized=True,
            )
        rejections.append(
            {
                "source": "fallback",
                "reason": "fallback (54) capture invalid after cleaning",
                "sample": fb1.excerpt(120),
            }
        )

    # 3) fallback: "Title:" label line (rare, but cheap)
    fb2 = _linear_find_group1_as_raw(
        doc,
        TITLE_LABEL_FALLBACK_PAT,
        kind=EntityKind.TITLE,
        sep=sep,
        order=order,
        confidence=0.2,
        meta={"rule": "title:fallback Title: label", "rejections": rejections},
    )
    if fb2 and (fb2.text or "").strip():
        clean = _clean_title_text(fb2.text)
        if _title_valid(clean):
            return fb2.normalize_to(
                value=clean,
                kind=EntityKind.TITLE,
                system="PDF",
                rule="title:fallback-label",
                normalized=True,
                rejections=rejections,
            )

    return None
