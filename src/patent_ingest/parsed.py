from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Generic, Optional, TypeVar, Any, Dict, Union
from enum import Enum

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Where, format_where

T = TypeVar("T")


class INIDKind(Enum):
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
    _86 = "86"
    _87 = "87"

    @classmethod
    def from_code(cls, code: str) -> Optional["INIDKind"]:
        key = f"_{code}"
        return cls.__members__.get(key)


class EntityKind(Enum):
    # “Semantic entities” you’ll want across jurisdictions / templates
    TITLE = "TITLE"
    ABSTRACT = "ABSTRACT"
    INVENTOR = "INVENTOR"
    ASSIGNEE = "ASSIGNEE"
    APPLICANT = "APPLICANT"
    ORGANIZATION = "ORGANIZATION"
    DATE = "DATE"
    PATENT_ID = "PATENT_ID"
    APPLICATION_ID = "APPLICATION_ID"
    IPC_CLASS = "IPC_CLASS"
    CPC_CLASS = "CPC_CLASS"
    ADDRESS = "ADDRESS"
    UNKNOWN = "UNKNOWN"


Kind = Union[INIDKind, EntityKind]


def kind_display(kind: Kind) -> str:
    """
    Human-readable label, stable across enums.
      INIDKind._54 -> "INID(54)"
      EntityKind.TITLE -> "TITLE"
    """
    if isinstance(kind, INIDKind):
        return f"INID({kind.value})"
    return kind.value


def kind_code(kind: Kind) -> Optional[str]:
    """
    Returns the INID 2-digit code if kind is INID, else None.
    """
    return kind.value if isinstance(kind, INIDKind) else None


def is_inid(kind: Kind, code: str | None = None) -> bool:
    if not isinstance(kind, INIDKind):
        return False
    return True if code is None else (kind.value == code)


def assert_evidence_matches(
    raw: ParsedRaw[str], doc: MultiPage, *, joiner: str = ""
) -> None:
    ev = raw.evidence(doc, joiner=joiner)
    if ev != raw.text:
        raise AssertionError(
            f"Evidence mismatch: evidence={ev!r} vs stored={raw.text!r}"
        )


T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True)
class ParsedRaw(Generic[T]):
    kind: Kind
    where: Where
    text: T  # typically str
    confidence: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    # ---- Evidence helpers ----
    def evidence(self, doc: MultiPage, *, joiner: str = "") -> str:
        """
        Reconstruct the referenced text from the document.
        Use this for assertions/debugging; for extraction use .text.
        """
        return doc.slice_where(self.where, joiner=joiner)

    def excerpt(self, max_len: int = 120) -> str:
        """
        Short printable excerpt of the raw text for logs.
        """
        s = str(self.text)
        s = " ".join(s.split())  # collapse whitespace for readability
        return s if len(s) <= max_len else s[: max_len - 1] + "…"

    # ---- Construction helpers ----
    def with_text(
        self, text: T, *, confidence: Optional[float] = None, **meta_updates: Any
    ) -> "ParsedRaw[T]":
        """
        Return a modified copy with new text and optional confidence/meta updates.
        """
        new_meta = dict(self.meta)
        new_meta.update(meta_updates)
        return ParsedRaw(
            kind=self.kind,
            where=self.where,
            text=text,
            confidence=self.confidence if confidence is None else confidence,
            meta=new_meta,
        )

    def with_meta(self, **meta_updates: Any) -> "ParsedRaw[T]":
        new_meta = dict(self.meta)
        new_meta.update(meta_updates)
        return replace(self, meta=new_meta)

    def retag(
        self, kind: Kind, *, confidence: Optional[float] = None, **meta_updates: Any
    ) -> "ParsedRaw[T]":
        """
        Same evidence and text, but a different semantic kind.
        Useful when you first capture as INID(54) then decide it’s TITLE.
        """
        new_meta = dict(self.meta)
        new_meta.update(meta_updates)
        return ParsedRaw(
            kind=kind,
            where=self.where,
            text=self.text,
            confidence=self.confidence if confidence is None else confidence,
            meta=new_meta,
        )

    # ---- Manual normalization entry point ----
    def normalize_to(
        self,
        value: U,
        *,
        kind: Kind | None = None,
        confidence: Optional[float] = None,
        system: Optional[str] = None,
        rule: Optional[str] = None,
        **meta_updates: Any,
    ) -> "ParsedNorm[U]":
        """
        Manual normalization: you provide the canonical value; we produce ParsedNorm.
        Optionally override kind (e.g. INID(11) -> PATENT_ID).
        """
        new_meta = dict(self.meta)
        if system is not None:
            new_meta["system"] = system
        if rule is not None:
            new_meta["rule"] = rule
        new_meta.update(meta_updates)

        return ParsedNorm(
            kind=self.kind if kind is None else kind,
            where=self.where,
            raw_text=str(self.text),
            value=value,
            confidence=self.confidence if confidence is None else confidence,
            meta=new_meta,
        )

    def __str__(self) -> str:
        return (
            f"{kind_display(self.kind)} @{format_where(self.where)}: {self.excerpt()}"
        )


@dataclass(frozen=True)
class ParsedNorm(Generic[U]):
    kind: Kind
    where: Where
    raw_text: str
    value: U
    confidence: Optional[float] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    # ---- Evidence helpers ----
    def evidence(self, doc: MultiPage, *, joiner: str = "") -> str:
        return doc.slice_where(self.where, joiner=joiner)

    def excerpt(self, max_len: int = 120) -> str:
        s = " ".join(self.raw_text.split())
        return s if len(s) <= max_len else s[: max_len - 1] + "…"

    # ---- Canonical formatting ----
    def canonical(self) -> str:
        """
        Returns a canonical string form when possible.
        If the value object implements .compact() or .canonical(), use it.
        Else fall back to str(value).
        """
        v = self.value
        if hasattr(v, "canonical") and callable(getattr(v, "canonical")):
            return getattr(v, "canonical")()
        if hasattr(v, "compact") and callable(getattr(v, "compact")):
            return getattr(v, "compact")()
        return str(v)

    def human(self) -> str:
        """
        Human-friendly formatting where possible.
        """
        v = self.value
        if hasattr(v, "human") and callable(getattr(v, "human")):
            return getattr(v, "human")()
        return str(v)

    # ---- Transformation helpers ----
    def map_value(
        self,
        fn,
        *,
        rule: Optional[str] = None,
        system: Optional[str] = None,
        confidence: Optional[float] = None,
        **meta_updates: Any,
    ) -> "ParsedNorm[Any]":
        """
        Transform the canonical value while preserving evidence.
        Useful for post-normalization adjustments (e.g., enforce uppercase, strip, etc.).
        """
        new_meta = dict(self.meta)
        if system is not None:
            new_meta["system"] = system
        if rule is not None:
            new_meta["rule"] = rule
        new_meta.update(meta_updates)

        return ParsedNorm(
            kind=self.kind,
            where=self.where,
            raw_text=self.raw_text,
            value=fn(self.value),
            confidence=self.confidence if confidence is None else confidence,
            meta=new_meta,
        )

    def with_meta(self, **meta_updates: Any) -> "ParsedNorm[U]":
        new_meta = dict(self.meta)
        new_meta.update(meta_updates)
        return replace(self, meta=new_meta)

    def retag(
        self, kind: Kind, *, confidence: Optional[float] = None, **meta_updates: Any
    ) -> "ParsedNorm[U]":
        new_meta = dict(self.meta)
        new_meta.update(meta_updates)
        return ParsedNorm(
            kind=kind,
            where=self.where,
            raw_text=self.raw_text,
            value=self.value,
            confidence=self.confidence if confidence is None else confidence,
            meta=new_meta,
        )

    def __str__(self) -> str:
        return f"{kind_display(self.kind)} @{format_where(self.where)}: {self.human()} (from {self.excerpt()})"
