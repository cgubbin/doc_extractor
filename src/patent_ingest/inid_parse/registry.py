from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator

from patent_ingest.diagnostics import Diagnostics
from patent_ingest.structured_logger import get_logger
from patent_ingest.model.analysis import InidResult


# ---------- enums ----------
class INIDKind(str, Enum):
    # Keep as codes: stable + easy mapping from "(54)" -> INIDKind
    _10 = "10"
    _12 = "12"
    _21 = "21"
    _22 = "22"
    _45 = "45"
    _51 = "51"
    _52 = "52"
    _54 = "54"
    _56 = "56"
    _57 = "57"
    _58 = "58"
    _63 = "63"
    _65 = "65"
    _71 = "71"
    _72 = "72"
    _73 = "73"
    _74 = "74"
    _75 = "75"
    _86 = "86"
    _87 = "87"

    @classmethod
    def from_code(cls, code: str) -> Optional["INIDKind"]:
        # normalize input like "(54)" or "54"
        c = code.strip()
        if c.startswith("(") and c.endswith(")"):
            c = c[1:-1].strip()
        key = f"_{c}"
        return cls.__members__.get(key)


# ---------- policy + errors ----------
class MissingRequiredINIDs(ValueError):
    """Raised when required INIDs are missing under the configured policy."""


class ParsePolicy(BaseModel):
    """
    Policy for early/fast validation (before expensive downstream parsing).

    Note: this policy is intentionally minimal at first; you can extend later with:
      - which tags are required vs optional
      - per-tag minimum length thresholds
      - presence requirements by doc type
    """

    model_config = ConfigDict(frozen=True)

    require_title: bool = True  # (54)
    require_inventors_or_assignee: bool = False  # require (75) or (73)
    require_pub_id: bool = False  # (10) or (12) typically in headers
    require_application_id: bool = False  # (21)
    require_abstract: bool = False  # (57) typically in headers

    # When True, unknown INIDs produce warnings. When False, silently ignore.
    warn_on_unknown_inids: bool = True

    # Treat empty/whitespace-only strings as missing
    empty_is_missing: bool = True

    fail_fast: bool = True


# ---------- models ----------
class ParsedInidRegistry(BaseModel):
    """
    Result of the *initial* registry parse: a typed map of INIDKind -> raw text.
    This is not yet the "typed semantic parse"; it's the stable hand-off object.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    data: dict[INIDKind, str] = Field(default_factory=dict)
    pages: list[int]
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)

    @field_validator("data")
    @classmethod
    def _strip_values(cls, v: dict[INIDKind, str]) -> dict[INIDKind, str]:
        # normalize raw strings lightly (strip trailing whitespace)
        out: dict[INIDKind, str] = {}
        for k, s in v.items():
            out[k] = s.strip() if isinstance(s, str) else s
        return out

    def get(self, kind: INIDKind, default: str = "") -> str:
        return self.data.get(kind, default)

    def has(self, kind: INIDKind) -> bool:
        s = self.data.get(kind)
        return bool(s and s.strip())

    def has_any(self, *kinds: INIDKind) -> bool:
        return any(self.has(k) for k in kinds)


# ---------- registry parse ----------
def parse_inid_registry(raw: InidResult, *, policy: ParsePolicy) -> ParsedInidRegistry:
    """
    Phase-0: map raw INIDs into INIDKind -> text, emit diagnostics, and
    enforce requiredness (presence/emptiness only).
    """
    diag = Diagnostics()
    out: dict[INIDKind, str] = {}

    logger = get_logger(__name__)

    # --- map raw tags to INIDKind ---
    for tag in raw.fields:
        logger.debug("processing_inid_tag", tag=tag)
        kind = INIDKind.from_code(str(tag))
        logger.debug("processing_inid_kind", kind=kind)
        if kind is None:
            if policy.warn_on_unknown_inids:
                diag.warn(
                    "front_matter.unexpected_inid",
                    f"Unknown INID code in raw parse: {tag}",
                )
            continue

        val = raw.fields[tag]
        if val is None:
            continue

        s = str(val)
        if policy.empty_is_missing and not s.strip():
            continue

        out[kind] = s

    logger.debug("registry_parse_result", data=out, pages=raw.pages)
    res = ParsedInidRegistry(data=out, pages=raw.pages, diagnostics=diag)

    # --- policy checks (presence/emptiness only) ---
    missing: list[tuple[str, str | None]] = []

    def require(cond: bool, code: str, msg: str, *, inid: str | None = None) -> None:
        if cond:
            return
        diag.error(code, msg, inid=inid)
        missing.append((msg, inid))

    if policy.require_title:
        require(
            res.has(INIDKind._54),
            "front_matter.missing_required_inid",
            "Missing (54) title",
            inid="54",
        )

    if policy.require_abstract:
        require(
            res.has(INIDKind._57),
            "front_matter.missing_required_inid",
            "Missing (57) abstract",
            inid="57",
        )

    if policy.require_inventors_or_assignee:
        require(
            res.has_any(INIDKind._75, INIDKind._73),
            "front_matter.missing_required_inid",
            "Missing (75) inventors or (73) assignee",
            inid="75",
        )

    if policy.require_pub_id:
        require(
            res.has_any(INIDKind._10, INIDKind._12),
            "front_matter.missing_required_inid",
            "Missing (10) or (12) publication id",
            inid="10",
        )

    if policy.require_application_id:
        require(
            res.has(INIDKind._21),
            "front_matter.missing_required_inid",
            "Missing (21) application number",
            inid="21",
        )

    if missing and policy.fail_fast:
        raise MissingRequiredINIDs(res.diagnostics.as_("text"))

    logger.debug("parsed_inid_registry_completed")

    return res
