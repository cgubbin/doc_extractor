from dataclasses import dataclass
from pathlib import Path
import json
from typing import Any

from doc_extractor.body.claims import (
    align_claims,
    diff_claims,
    Claim,
)
from doc_extractor.structured_logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PatentMeta:
    id: str
    application_number: str
    assignee: str
    filed_date: str
    grant_date: str
    inventors: list[str]
    title: str
    abstract: str
    references: list[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PatentMeta":
        """Load from v1.1 bundle format (matches bundle_v1_1.FrontMatterV1_1)."""
        ident = d.get("identification", {})
        app = d.get("application", {})
        parties = d.get("parties", {})
        tech = d.get("technical", {})
        return cls(
            id=ident.get("publication", {}).get("primary", ""),
            application_number=app.get("application_number", {}).get("primary", ""),
            assignee=parties.get("assignee", ""),
            inventors=parties.get("inventors", []),
            filed_date=app.get("filing_date", ""),
            grant_date=app.get("grant_date", ""),
            title=tech.get("title", ""),
            abstract=tech.get("abstract", ""),
            references=tech.get("references", []),
        )


@dataclass(frozen=True)
class PatentSections:
    background: str
    detailed_description: str
    summary: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PatentSections":
        return cls(
            background=d.get("background", "") or "",
            detailed_description=d.get("detailed_description", "") or "",
            summary=d.get("summary", "") or "",
        )


class FigureDescription:
    description: str
    number: int
    suffix: str

    def __init__(self, data: dict):
        self.description = data.get("description", "")
        self.number = data.get("figure_number", 0)
        self.suffix = data.get("figure_suffix", "")


@dataclass(frozen=True)
class PatentDocument:
    pdf_path: str
    doc_id: str
    sha256: str
    schema_version: str
    date_created: str
    data_dir: str
    sheet_pngs: list[str]
    figure_pngs: list[str]
    meta: PatentMeta
    sections: PatentSections
    claims: list[Claim]
    figure_descriptions: list[FigureDescription]
    diagnostics: dict


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def load_patent(processed_dir: str) -> PatentDocument:
    p = Path(processed_dir)
    manifest = _read_json(p / "manifest.json")
    sections = _read_json(p / manifest["artifacts"]["sections"])
    claims = _read_json(p / manifest["artifacts"]["claims"])
    figures = _read_json(p / manifest["artifacts"]["figures"])
    meta = _read_json(p / manifest["artifacts"]["metadata"])

    # Optional image artifacts (may not be present if export_figure_pngs=False)
    figure_pngs = manifest["artifacts"].get("figure_pngs", [])
    sheet_pngs = manifest["artifacts"].get("sheet_pngs", [])

    return PatentDocument(
        pdf_path=manifest["pdf_path"],
        doc_id=manifest["doc_id"],
        sha256=manifest["sha256"],
        schema_version=manifest["schema_version"],
        date_created=manifest["created_utc"],
        data_dir=str(p),
        meta=PatentMeta.from_dict(meta),
        sections=PatentSections.from_dict(sections),
        claims=[Claim.from_dict(each) for each in claims],
        figure_descriptions=[FigureDescription(f) for f in figures],
        figure_pngs=figure_pngs,
        sheet_pngs=sheet_pngs,
        diagnostics=manifest.get("diagnostics", {}),
    )


def compare_patent_versions(
    submitted: PatentDocument,
    approved: PatentDocument,
    out_dir: str,
    *,
    excerpt_window_chars: int = 600,
    max_excerpts_per_section: int = 25,
    match_threshold: float = 0.72,
    unchanged_threshold: float = 0.96,
) -> dict:
    out = Path(out_dir)
    meta_dir = out / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    #
    pairs, un_sub, un_app = align_claims(
        submitted.claims, approved.claims, match_threshold
    )
    diffres = diff_claims(
        submitted.claims,
        approved.claims,
        pairs,
        un_sub,
        un_app,
        unchanged_threshold,
    )

    logger.info("claims_diff_computed", diff_result=str(diffres))
    # sub_text = Path(submitted.normalized_text_path).read_text(
    #     encoding="utf-8", errors="replace"
    # )
    # app_text = Path(approved.normalized_text_path).read_text(
    #     encoding="utf-8", errors="replace"
    # )
    #
    # sub_ex = extract_relevant_excerpts(
    #     sub_text,
    #     diffres,
    #     "submitted",
    #     excerpt_window_chars,
    #     max_excerpts_per_section,
    # )
    # app_ex = extract_relevant_excerpts(
    #     app_text,
    #     diffres,
    #     "approved",
    #     excerpt_window_chars,
    #     max_excerpts_per_section,
    # )
    #
    # bundle = {
    #     "submitted_doc_id": submitted.doc_id,
    #     "approved_doc_id": approved.doc_id,
    #     "claims_diff": {
    #         "summary": diffres.summary,
    #         "alignments": [a.__dict__ for a in diffres.alignments],
    #         "warnings": [w.__dict__ for w in diffres.warnings],
    #     },
    #     "relevant_excerpts": {
    #         "submitted": [e.__dict__ for e in sub_ex],
    #         "approved": [e.__dict__ for e in app_ex],
    #     },
    # }
    # (meta_dir / "claims_diff.json").write_text(
    #     json.dumps(bundle["claims_diff"], indent=2), encoding="utf-8"
    # )
    # (meta_dir / "relevant_excerpts.json").write_text(
    #     json.dumps(bundle["relevant_excerpts"], indent=2), encoding="utf-8"
    # )
    # (meta_dir / "comparison_bundle.json").write_text(
    #     json.dumps(bundle, indent=2), encoding="utf-8"
    # )
    # return bundle
