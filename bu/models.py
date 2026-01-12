from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Literal


@dataclass
class WarningItem:
    code: str
    message: str


@dataclass
class SectionSpan:
    name: str
    start: int
    end: int
    confidence: float


@dataclass
class FigureAsset:
    path: str
    source: Literal["embedded", "rendered"]
    page: Optional[int] = None
    note: Optional[str] = None


@dataclass
class Claim:
    number: int
    text: str
    depends_on: list[int] = field(default_factory=list)
    is_independent: bool = True


@dataclass
class PatentDocument:
    pdf_path: str
    doc_id: str
    sha256: str
    out_dir: str

    raw_text_path: str
    normalized_text_path: str

    figures: list[FigureAsset] = field(default_factory=list)
    sections: dict[str, SectionSpan] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)


@dataclass
class ClaimAlignment:
    submitted_no: Optional[int]
    approved_no: Optional[int]
    status: Literal["added", "removed", "modified", "unchanged", "renumbered"]
    similarity: float
    diff: dict


@dataclass
class ClaimsDiffResult:
    alignments: list[ClaimAlignment]
    summary: dict
    warnings: list[WarningItem] = field(default_factory=list)


@dataclass
class RelevantExcerpt:
    source: Literal["submitted", "approved"]
    section: str
    start: int
    end: int
    text: str
    reason: str
    score: float
