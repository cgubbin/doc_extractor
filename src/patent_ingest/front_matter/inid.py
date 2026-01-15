from dataclasses import dataclass
import re
from typing import Callable, Optional, Any
from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.model.mapping import (
    linearize,
    trim_global_range,
    global_range_to_where,
)
from patent_ingest.parsed import ParsedRaw, INIDKind, Kind


@dataclass(frozen=True)
class Validation:
    ok: bool
    reason: Optional[str] = None


def ok() -> Validation:
    return Validation(True, None)


def bad(reason: str) -> Validation:
    return Validation(False, reason)


INID_MARKER_PAT = re.compile(r"\(\s*(\d{2})\s*\)")


@dataclass(frozen=True)
class ParsedINIDBlocks:
    inid_blocks: dict[INIDKind, ParsedRaw[str]]

    def __getitem__(self, kind: INIDKind) -> ParsedRaw[str]:
        return self.inid_blocks[kind]


def prefer_inid_else(
    *,
    inid: dict[INIDKind, ParsedRaw[str]],
    prefer: tuple[INIDKind, ...],
    as_kind: Kind,
    fallback: Callable[[], Optional[ParsedRaw[str]]],
    rule: str,
) -> Optional[ParsedRaw[str]]:
    # 1) Try INID candidates in order
    for k in prefer:
        raw = inid.get(k)
        if raw and str(raw.text).strip():
            return raw.retag(as_kind, rule=rule, source="inid", inid_code=k.value)

    # 2) Fallback
    fb = fallback()
    if fb:
        return fb.retag(as_kind, rule=rule, source="fallback")
    return None


Validator = Callable[[str], Validation]


def prefer_inid_if_valid_else(
    *,
    inid: dict[INIDKind, ParsedRaw[str]],
    prefer: tuple[INIDKind, ...],
    as_kind: Kind,
    validator: Validator,
    fallback: Callable[[], Optional[ParsedRaw[str]]],
    rule: str,
) -> Optional[ParsedRaw[str]]:
    rejections: list[dict[str, Any]] = []

    # 1) INID candidates
    for k in prefer:
        raw = inid.get(k)
        if not raw:
            continue

        candidate = str(raw.text).strip()
        if not candidate:
            rejections.append({"source": "inid", "inid": k.value, "reason": "empty"})
            continue

        v = validator(candidate)
        if v.ok:
            return raw.retag(
                as_kind,
                rule=rule,
                source="inid",
                inid_code=k.value,
                validated=True,
            ).with_meta(rejections=rejections)

        # invalid -> record and keep searching / fall back
        rejections.append(
            {
                "source": "inid",
                "inid": k.value,
                "reason": v.reason,
                "sample": raw.excerpt(80),
            }
        )

    # 2) fallback
    fb = fallback()
    if fb:
        # You may also want to validate fallback; usually yes.
        v = validator(str(fb.text))
        if v.ok:
            return fb.retag(
                as_kind,
                rule=rule,
                source="fallback",
                validated=True,
            ).with_meta(rejections=rejections)

        # fallback exists but invalid too
        return fb.retag(
            as_kind,
            rule=rule,
            source="fallback",
            validated=False,
        ).with_meta(rejections=rejections, validation_error=v.reason)

    return None


def parse_inid_blocks_raw(
    doc: MultiPage,
    *,
    sep: str = "\n",
    order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
    marker_pat: re.Pattern[str] = INID_MARKER_PAT,
    trim: bool = True,
    confidence: float | None = 0.7,
) -> ParsedINIDBlocks:
    """
    Extract INID blocks into ParsedRaw objects.
    Keys are INIDKind (e.g., INIDKind._54). Unknown codes are skipped by default.
    """
    linear_text, segments = linearize(doc, sep=sep, order=order)
    matches = list(marker_pat.finditer(linear_text))

    out: dict[INIDKind, ParsedRaw[str]] = {}

    for i, m in enumerate(matches):
        code = m.group(1)  # "54"
        kind = INIDKind.from_code(code)
        if kind is None:
            # Unknown INID code; choose: skip, or store as EntityKind.UNKNOWN, or create a dynamic kind.
            # I recommend: skip OR store in meta under UNKNOWN.
            continue

        raw_start = m.end()
        raw_end = matches[i + 1].start() if i + 1 < len(matches) else len(linear_text)

        start, end = (
            trim_global_range(linear_text, raw_start, raw_end)
            if trim
            else (raw_start, raw_end)
        )
        if end <= start:
            continue

        text = linear_text[start:end]
        if not text:
            continue

        where = global_range_to_where(start, end, segments)

        # First occurrence wins, like your original function
        if kind not in out:
            out[kind] = ParsedRaw[str](
                kind=kind,
                where=where,
                text=text,
                confidence=confidence,
                meta={
                    "inid_code": code,
                    "global": (start, end),
                    "marker_span": (m.start(), m.end()),
                    "reading_order": [c.value for c in order],
                },
            )

    return out
