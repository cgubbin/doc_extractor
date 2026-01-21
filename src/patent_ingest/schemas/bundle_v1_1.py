"""
Patent Bundle Schema v1.1

Defines the unified output format for patent parsing bundles.
Ensures round-trip consistency between save (export_artifacts) and load (load_processed_doc).

Bundle Structure:
  {doc_id}/
    manifest.json          - Bundle metadata, artifact paths, diagnostics
    front/metadata.json    - Front matter fields
    body/sections.json     - Patent body sections
    body/claims.json       - Parsed claims list
    body/figures.json      - Figure descriptions/references
    drawings/sheets/*.png  - Sheet images (optional)
    drawings/regions/*.png - Figure region crops (optional)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Literal

SCHEMA_VERSION = "1.1.0"


@dataclass(frozen=True)
class BundleManifest:
    """Bundle-level metadata and artifact inventory.

    Saved as: {doc_id}/manifest.json
    """
    doc_id: str
    schema_version: str  # "1.1.0"
    pdf_path: str | None
    pdf_sha256: str
    created_utc: str  # ISO 8601 date
    elapsed_time_ms: float  # Processing time in milliseconds
    artifacts: dict[str, Any]  # Maps artifact type -> path or list of paths
    diagnostics: dict[str, Any]  # Structured diagnostics from parsing

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "schema_version": self.schema_version,
            "pdf_path": self.pdf_path,
            "pdf_sha256": self.pdf_sha256,
            "created_utc": self.created_utc,
            "elapsed_time_ms": self.elapsed_time_ms,
            "artifacts": self.artifacts,
            "diagnostics": self.diagnostics,
        }


@dataclass(frozen=True)
class FrontMatterV1_1:
    """Front matter parsed fields.

    Saved as: {doc_id}/front/metadata.json
    """
    # Core identification
    patent_number_normalized: str  # e.g., "US10935501B2" (FIXED spelling from load.py)
    title: str

    # Filing & grant info
    application_number: str  # e.g., "16/123,456"
    filed_date: str  # ISO 8601: "2019-01-15"
    grant_date: str  # ISO 8601: "2021-03-02"

    # Parties
    assignee: str  # Primary assignee
    inventors: list[str]  # List of inventor names

    # Content metadata
    abstract: str  # Abstract text (ADDED for completeness)
    reported_claim_count: int
    reported_drawing_sheet_count: int

    # Citations
    cited_us_patents: list[str]  # US grant numbers (digits only)
    cited_us_publications: list[str]  # US publication numbers

    # Parsing metadata
    num_sheets: int  # Number of front matter pages scanned

    def to_dict(self) -> dict[str, Any]:
        return {
            "patent_number_normalized": self.patent_number_normalized,
            "title": self.title,
            "application_number": self.application_number,
            "filed_date": self.filed_date,
            "grant_date": self.grant_date,
            "assignee": self.assignee,
            "inventors": self.inventors,
            "abstract": self.abstract,
            "reported_claim_count": self.reported_claim_count,
            "reported_drawing_sheet_count": self.reported_drawing_sheet_count,
            "cited_us_patents": self.cited_us_patents,
            "cited_us_publications": self.cited_us_publications,
            "num_sheets": self.num_sheets,
        }


@dataclass(frozen=True)
class BodySectionsV1_1:
    """Major patent body sections.

    Saved as: {doc_id}/body/sections.json
    """
    background: str  # Background section text
    summary: str  # Summary section text
    detailed_description: str  # Detailed description text

    def to_dict(self) -> dict[str, Any]:
        return {
            "background": self.background,
            "summary": self.summary,
            "detailed_description": self.detailed_description,
        }


@dataclass(frozen=True)
class ClaimV1_1:
    """Single patent claim.

    Part of: {doc_id}/body/claims.json (list of these)
    """
    number: int  # Claim number (1-indexed)
    text: str  # Full claim text
    depends_on: list[int]  # List of claim numbers this depends on
    is_independent: bool  # True if independent claim

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "text": self.text,
            "depends_on": self.depends_on,
            "is_independent": self.is_independent,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClaimV1_1:
        return cls(
            number=d.get("number", 0),
            text=d.get("text", ""),
            depends_on=d.get("depends_on", []),
            is_independent=d.get("is_independent", True),
        )


@dataclass(frozen=True)
class FigureDescriptionV1_1:
    """Drawing figure description/reference.

    Part of: {doc_id}/body/figures.json (list of these)
    """
    figure_number: int  # Figure number (e.g., 3 for "FIG. 3A")
    figure_suffix: str  # Optional suffix (e.g., "A" for "FIG. 3A")
    description: str  # Associated description text

    def to_dict(self) -> dict[str, Any]:
        return {
            "figure_number": self.figure_number,
            "figure_suffix": self.figure_suffix,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FigureDescriptionV1_1:
        return cls(
            figure_number=d.get("figure_number", 0),
            figure_suffix=d.get("figure_suffix", ""),
            description=d.get("description", ""),
        )


# JSON Schema definitions for validation (optional but recommended)

MANIFEST_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["doc_id", "schema_version", "pdf_sha256", "created_utc", "artifacts"],
    "properties": {
        "doc_id": {"type": "string"},
        "schema_version": {"type": "string", "const": "1.1.0"},
        "pdf_path": {"type": ["string", "null"]},
        "pdf_sha256": {"type": "string"},
        "created_utc": {"type": "string", "format": "date"},
        "artifacts": {
            "type": "object",
            "properties": {
                "metadata": {"type": "string"},  # Path to front/metadata.json
                "sections": {"type": "string"},  # Path to body/sections.json
                "claims": {"type": "string"},    # Path to body/claims.json
                "figures": {"type": "string"},   # Path to body/figures.json
                "sheet_pngs": {"type": "array", "items": {"type": "string"}},
                "figure_pngs": {"type": "array", "items": {"type": "string"}},
            },
        },
        "diagnostics": {"type": "object"},
    },
}

FRONT_MATTER_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": [
        "patent_number_normalized",
        "title",
        "application_number",
        "filed_date",
        "grant_date",
        "assignee",
        "inventors",
    ],
    "properties": {
        "patent_number_normalized": {"type": "string"},
        "title": {"type": "string"},
        "application_number": {"type": "string"},
        "filed_date": {"type": "string"},
        "grant_date": {"type": "string"},
        "assignee": {"type": "string"},
        "inventors": {"type": "array", "items": {"type": "string"}},
        "abstract": {"type": "string"},
        "reported_claim_count": {"type": "integer"},
        "reported_drawing_sheet_count": {"type": "integer"},
        "cited_us_patents": {"type": "array", "items": {"type": "string"}},
        "cited_us_publications": {"type": "array", "items": {"type": "string"}},
        "num_sheets": {"type": "integer"},
    },
}

SECTIONS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "background": {"type": "string"},
        "summary": {"type": "string"},
        "detailed_description": {"type": "string"},
    },
}

CLAIM_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["number", "text"],
    "properties": {
        "number": {"type": "integer"},
        "text": {"type": "string"},
        "depends_on": {"type": "array", "items": {"type": "integer"}},
        "is_independent": {"type": "boolean"},
    },
}

FIGURE_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "figure_number": {"type": "integer"},
        "figure_suffix": {"type": "string"},
        "description": {"type": "string"},
    },
}
