import re
from typing import Any, Sequence, Optional

from patent_ingest.model.span import Span, Where, Position
from patent_ingest.parsed import ParsedRaw, INIDKind, EntityKind, ParsedNorm
from patent_ingest.front_matter.util import normalize_punctuation_spacing
from patent_ingest.diagnostics import Diagnostics

ASSIGNEE_HEADING_STOP_PAT = re.compile(
    r"\b("
    r"FOREIGN\s+PATENT\s+DOCUMENTS|"
    r"U\.S\.\s*PATENT\s*DOCUMENTS|"
    r"OTHER\s+PUBLICATIONS|"
    r"REFERENCES\s+CITED|"
    r"ABSTRACT|"
    r"Primary\s+Examiner|"
    r"Assistant\s+Examiner"
    r")\b",
    re.IGNORECASE,
)

ASSIGNEE_STOP_PAT = re.compile(
    r"(\(\*\)|\*|\bNotice\b\s*[:\-]|"
    r"\bSubject\s+to\s+any\s+disclaimer\b|"
    r"\bpatent\s+is\s+extended\s+or\s+adjusted\b)",
    re.IGNORECASE,
)

ASSIGNEE_FOREIGN_REF_STOP_PAT = re.compile(
    r"\b(EP|WO|PCT|KR|JP|CN|DE|FR|GB|CA|TW|RU|BR|IN|AU|IT|ES|NL|SE|CH)\b\s*[-A-Z0-9]",
    re.IGNORECASE,
)

ASSIGNEE_CONTINUED_PAT = re.compile(r"\bContinued\b|\(\s*Continued\s*\)", re.IGNORECASE)

COUNTRY_TAG_PAT = re.compile(r"\(\s*[A-Z]{2}\s*\)\s*$")  # (US) at end


def _cut_at_earliest_with_idx(
    s: str, patterns: Sequence[re.Pattern[str]]
) -> tuple[str, int]:
    """
    Returns (cut_text, end_index_in_original_s).
    If no stop matches, end_index = len(s).
    """
    if not s:
        return s, 0
    stops: list[int] = []
    for pat in patterns:
        m = pat.search(s)
        if m:
            stops.append(m.start())
    if not stops:
        return s.strip(), len(s)
    end = min(stops)
    return s[:end].strip(), end


def _strip_leading_label_with_idx(s: str, labels: list[str]) -> tuple[str, int]:
    """
    Strip a leading label and return (new_string, start_index_in_original).
    """
    if not s:
        return s, 0

    lead_ws = len(s) - len(s.lstrip())
    ss = s.lstrip()

    for lab in labels:
        if ss.lower().startswith(lab.lower()):
            cut = ss[len(lab) :]
            cut2 = cut.lstrip(" :\t\r\n")
            start_idx = lead_ws + len(lab) + (len(cut) - len(cut2))
            return cut2, start_idx

    return s, 0


def _refine_where_by_slice(
    raw: ParsedRaw[str], start_idx: int, end_idx: int
) -> tuple[Where, dict[str, Any]]:
    """
    Refine where for substring raw.text[start_idx:end_idx] if where is Span.
    If MultiSpan, keep it and record indices.
    """
    meta: dict[str, Any] = {"refine": {"start_idx": start_idx, "end_idx": end_idx}}

    if isinstance(raw.where, Span):
        new_start = Position(
            raw.where.start.page,
            raw.where.start.column,
            raw.where.start.offset + start_idx,
        )
        new_end = Position(
            raw.where.end.page, raw.where.end.column, raw.where.start.offset + end_idx
        )
        return Span(new_start, new_end), meta

    return raw.where, meta


def _clean_assignee_from_inid(raw: ParsedRaw[str]) -> ParsedRaw[str]:
    """
    Apply your old cleaning rules, attempting span refinement when possible.
    """
    original = raw.text or ""
    s = original

    # 0) strip leading label
    s1, strip_idx = _strip_leading_label_with_idx(
        s, ["Assignee", "Assignees", "Assignee:"]
    )

    # 0.5) punctuation spacing normalization if you have it
    # If you don't have normalize_punctuation_spacing, replace with s1 = " ".join(s1.split())
    try:
        s1n = normalize_punctuation_spacing(s1).strip()
    except NameError:
        s1n = " ".join(s1.split()).strip()

    # 1) cut at headings/refs/boilerplate
    s2, cut_end_rel = _cut_at_earliest_with_idx(
        s1n,
        [
            ASSIGNEE_HEADING_STOP_PAT,
            ASSIGNEE_FOREIGN_REF_STOP_PAT,
            ASSIGNEE_CONTINUED_PAT,
            ASSIGNEE_STOP_PAT,
        ],
    )

    # 2) strip trailing country tag LAST (may shorten further)
    # Need to compute resulting end index if the tag is removed.
    s3 = COUNTRY_TAG_PAT.sub("", s2).strip()

    # 3) final tidy
    s4 = s3.rstrip(" ,;.")

    # If everything got removed
    if not s4:
        return raw.with_text("", cleaned=True)

    # Compute approximate end index mapping for refinement.
    # We can refine precisely up to the s2 cut point relative to s1n.
    # COUNTRY_TAG removal + rstrip punctuation makes exact end hard; record that in meta.
    start_idx = strip_idx + (
        len(s1) - len(s1.lstrip())
    )  # best-effort; label strip already handled
    # Better: compute where s1n starts inside s1 (we stripped and normalized), but normalization can shift indices.
    # So we refine only using label stripping + heading cut indices based on s1n string length.
    # We'll keep it conservative: refine start at strip_idx, end at strip_idx + cut_end_rel, and record post-ops.
    end_idx = strip_idx + cut_end_rel

    where2, refine_meta = _refine_where_by_slice(
        raw, start_idx=strip_idx, end_idx=end_idx
    )

    return ParsedRaw[str](
        kind=raw.kind,
        where=where2,
        text=s4,
        confidence=raw.confidence,
        meta={
            **raw.meta,
            **refine_meta,
            "cleaned": True,
            "note": "span refinement conservative; country-tag/punct tidy may further shorten text",
        },
    )


def extract_assignee(
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
    diag: Diagnostics,
) -> Optional[ParsedNorm[str]]:
    """
    Same behavior as your original new-model extract_assignee(), but with Diagnostics added.

    Preference:
      - INID(73) assignee
      - else INID(71) applicant
      - else None

    Behavior is unchanged:
      - If INID exists but cleans to empty, we still return ParsedNorm[value=""] with normalized=False.

    Diagnostics:
      - WARN if neither INID is present (missing)
      - WARN if chosen INID cleans to empty (cleaned-empty)
    """
    field = "assignee"

    # 1) choose source block
    src: Optional[ParsedRaw[str]] = None
    used_inid: Optional[str] = None

    inid73 = inid_blocks.get(INIDKind._73) if hasattr(INIDKind, "_73") else None
    inid71 = inid_blocks.get(INIDKind._71) if hasattr(INIDKind, "_71") else None

    if inid73 and (inid73.text or "").strip():
        src = inid73
        used_inid = "73"
    elif inid71 and (inid71.text or "").strip():
        src = inid71
        used_inid = "71"
    else:
        diag.warn(
            "assignee.missing",
            "No assignee/applicant found in INID(73) or INID(71).",
            field=field,
        )
        return None

    # 2) retag + clean
    tagged = src.retag(
        EntityKind.ORGANIZATION,
        rule="assignee:from-inid",
        source="inid",
        inid_code=used_inid,
    )
    cleaned = _clean_assignee_from_inid(tagged)

    if not cleaned.text.strip():
        diag.warn(
            "assignee.cleaned_empty",
            "Assignee/applicant INID present but cleaned to empty (likely boilerplate/stop patterns).",
            field=field,
            where=cleaned.where,
            raw=(src.text or "")[:200],
            inid_code=used_inid,
        )
        return cleaned.normalize_to(
            value="",
            kind=EntityKind.ORGANIZATION,
            system="PDF",
            rule="assignee:cleaned-empty",
            normalized=False,
            inid_code=used_inid,
        )

    # 3) "normalize" (here: the cleaned string is already the normalized value)
    return cleaned.normalize_to(
        value=cleaned.text.strip(),
        kind=EntityKind.ORGANIZATION,
        system="PDF",
        rule="assignee:clean",
        normalized=True,
        inid_code=used_inid,
    )
