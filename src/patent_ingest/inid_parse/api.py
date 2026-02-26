from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from patent_ingest.diagnostics import Diagnostics
from patent_ingest.structured_logger import get_logger
from patent_ingest.model.analysis import InidResult

from .registry import ParsePolicy
from .parser import ParsedFrontMatter, parse_front_matter
from .semantic import ParsedFrontMatterV1, parse_front_matter_semantic


class InidPipelineResult(BaseModel):
    """
    Debug-friendly output that preserves intermediates.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # phase 0 (raw registry + requiredness)
    phase0: ParsedFrontMatter

    # semantic (cleaned + tokenized + structured)
    semantic: ParsedFrontMatterV1

    # merged diagnostics (semantic includes phase0 already, but this is convenient)
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)


def parse_inids(raw: InidResult, *, policy: ParsePolicy) -> ParsedFrontMatterV1:
    """
    Single-step public API:
      - registry parse (INIDKind -> raw text) + requiredness (fail-fast supported)
      - semantic parse (strip INID prefixes/labels, tokenize ids/classifications, structure fields)

    Returns semantic output only (the thing downstream should consume).
    """
    logger = get_logger(__name__)
    logger.info("raw_inid_parse_started")
    phase0 = parse_front_matter(raw, policy=policy)  # may raise MissingRequiredInids
    logger.info("semantic_inid_parse_started")
    semantic = parse_front_matter_semantic(phase0, policy=policy)
    return semantic


def parse_inids_debug(raw: InidResult, *, policy: ParsePolicy) -> InidPipelineResult:
    """
    Same as parse_inids(), but returns intermediates for debugging.
    """
    phase0 = parse_front_matter(raw, policy=policy)  # may raise MissingRequiredInids
    semantic = parse_front_matter_semantic(phase0, policy=policy)

    diag = Diagnostics()
    diag.merge(phase0.diagnostics)
    diag.merge(semantic.diagnostics)

    return InidPipelineResult(phase0=phase0, semantic=semantic, diagnostics=diag)
