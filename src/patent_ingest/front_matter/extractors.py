from typing import Optional

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.parsed import ParsedRaw, INIDKind, EntityKind
from patent_ingest.front_matter.inid import (
    prefer_inid_if_valid_else,
    prefer_inid_else,
    ok,
    bad,
    Validation,
)
from patent_ingest.front_matter.util import find_first_in_region

from patent_ingest.patent_id import US_PATENT_RE


import re

US_PATENT_VALID = re.compile(
    r"(?ix)\b(?:US\s*)?(?:RE|PP|D)?\s*\d[\d,\s]{5,}\d(?:\s*[A-Z]\d)?\b"
)


def validate_us_patent_text(text: str) -> Validation:
    s = " ".join(text.split())  # whitespace normalize
    return ok() if US_PATENT_VALID.search(s) else bad("no plausible US patent id found")


def get_patent_id_raw(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
) -> Optional[ParsedRaw[str]]:
    """
    Returns a ParsedRaw[str] with kind=EntityKind.PATENT_ID, either:
      - sourced from an INID block (preferred), or
      - found via fallback in page 0, right column (second column).
    """

    def fallback() -> Optional[ParsedRaw[str]]:
        return find_first_in_region(
            doc,
            page=0,
            column=Column.RIGHT,  # second column
            pat=US_PATENT_RE,
            kind=EntityKind.PATENT_ID,
            confidence=0.99,
            meta={"note": "fallback: first match in page0/right"},
        )

    # Prefer INID kinds if/when you add them. Common ones you might eventually use:
    # (11) publication/grant number, (21) application number, etc.
    # Put the ones you trust most first.
    prefer = tuple(
        k for k in (INIDKind._10,) if isinstance(k, INIDKind)
    )  # (keeps this snippet safe if not defined yet)

    return prefer_inid_if_valid_else(
        inid=inid_blocks,
        prefer=prefer,
        as_kind=EntityKind.PATENT_ID,
        validator=validate_us_patent_text,
        fallback=fallback,
        rule="patent-id:prefer-inid-else-fallback",
    )


def get_title_raw(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
) -> Optional[ParsedRaw[str]]:
    """
    Returns a ParsedRaw[str] with kind=EntityKind.PATENT_ID, either:
      - sourced from an INID block (preferred), or
      - found via fallback in page 0, right column (second column).
    """

    def fallback() -> Optional[ParsedRaw[str]]:
        raise NotImplementedError("No fallback for title implemented yet")

    # Prefer INID kinds if/when you add them. Common ones you might eventually use:
    # (11) publication/grant number, (21) application number, etc.
    # Put the ones you trust most first.
    prefer = tuple(
        k for k in (INIDKind._54,) if isinstance(k, INIDKind)
    )  # (keeps this snippet safe if not defined yet)

    return prefer_inid_else(
        inid=inid_blocks,
        prefer=prefer,
        as_kind=EntityKind.TITLE,
        fallback=fallback,
        rule="patent-id:prefer-inid-else-fallback",
    )


def get_application_id_raw(
    doc: MultiPage,
    inid_blocks: dict[INIDKind, ParsedRaw[str]],
) -> Optional[ParsedRaw[str]]:
    """
    Returns a ParsedRaw[str] with kind=EntityKind.PATENT_ID, either:
      - sourced from an INID block (preferred), or
      - found via fallback in page 0, right column (second column).
    """

    def fallback() -> Optional[ParsedRaw[str]]:
        return find_first_in_region(
            doc,
            page=0,
            column=Column.RIGHT,  # second column
            pat=US_PATENT_RE,
            kind=EntityKind.PATENT_ID,
            confidence=0.99,
            meta={"note": "fallback: first match in page0/right"},
        )

    # Prefer INID kinds if/when you add them. Common ones you might eventually use:
    # (11) publication/grant number, (21) application number, etc.
    # Put the ones you trust most first.
    prefer = tuple(
        k for k in (INIDKind._21,) if isinstance(k, INIDKind)
    )  # (keeps this snippet safe if not defined yet)

    return prefer_inid_else(
        inid=inid_blocks,
        prefer=prefer,
        as_kind=EntityKind.APPLICATION_ID,
        fallback=fallback,
        rule="patent-id:prefer-inid-else-fallback",
    )
