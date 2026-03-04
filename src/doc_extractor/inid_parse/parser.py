from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from doc_extractor.diagnostics import Diagnostics
from doc_extractor.model.analysis import InidResult

from .registry import (
    INIDKind,
    ParsedInidRegistry,
    ParsePolicy,
    MissingRequiredINIDs,
    parse_inid_registry,
)


class RawSemantic(BaseModel):
    """
    Very light 'semantic' view sourced directly from INID raw strings.
    This is intentionally minimal and will be replaced/augmented by the
    token-based semantic parser next.
    """

    model_config = ConfigDict(frozen=True)

    publication_id: Optional[str] = None  # (10)/(12) raw as-is
    application_number: Optional[str] = None  # (21)
    filing_date: Optional[str] = None  # (22)
    grant_date: Optional[str] = None  # (45)
    title: Optional[str] = None  # (54)
    abstract: Optional[str] = None  # (57)
    inventors: Optional[str] = None  # (75)
    assignee: Optional[str] = None  # (73)


class ParsedFrontMatter(BaseModel):
    """
    Top-level parse result (phase-0 + light structuring).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    inid: dict[INIDKind, str] = Field(default_factory=dict)
    pages: list[int] = Field(default_factory=list)
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)

    # lightweight convenience projection for immediate consumers
    raw_semantic: RawSemantic = Field(default_factory=RawSemantic)


def _build_raw_semantic(reg: ParsedInidRegistry) -> RawSemantic:
    # Prefer (10) if present else (12). (Some formats encode pub no/kind inconsistently.)
    pub = reg.data.get(INIDKind._10) or reg.data.get(INIDKind._12)
    inventors = reg.data.get(INIDKind._72) or reg.data.get(INIDKind._75)

    return RawSemantic(
        publication_id=pub.strip() if pub else None,
        application_number=(reg.data.get(INIDKind._21) or "").strip() or None,
        filing_date=(reg.data.get(INIDKind._22) or "").strip() or None,
        grant_date=(reg.data.get(INIDKind._45) or "").strip() or None,
        title=(reg.data.get(INIDKind._54) or "").strip() or None,
        abstract=(reg.data.get(INIDKind._57) or "").strip() or None,
        inventors=inventors.strip() or None,
        assignee=(reg.data.get(INIDKind._73) or "").strip() or None,
    )


def parse_front_matter(raw: InidResult, *, policy: ParsePolicy) -> ParsedFrontMatter:
    """
    Top-level front-matter parser.

    Phase-0 only:
      - Registry parse (INIDKind -> raw text)
      - Requiredness checks per policy (fail-fast supported)
      - Returns a ParsedFrontMatter with raw_semantic convenience fields

    Token extraction + typed semantic parsing will be layered on next.
    """
    from doc_extractor.structured_logger import get_logger

    logger = get_logger(__name__)

    try:
        logger.debug("registry_parse_started")
        reg = parse_inid_registry(raw, policy=policy)
    except MissingRequiredINIDs:
        # If fail_fast is set, parse_inid_registry raises; we still want to preserve
        # diagnostics for caller visibility if they catch the exception.
        raise
    raw_semantic = _build_raw_semantic(reg)
    fm = ParsedFrontMatter(
        inid=reg.data,
        pages=reg.pages,
        diagnostics=reg.diagnostics,
        raw_semantic=raw_semantic,
    )
    logger.debug("parse_front_matter_completed")

    # Optional: if you want a hard stop on *any* errors even when fail_fast is False
    # you can add another policy flag later and raise here based on diagnostics.
    return fm
