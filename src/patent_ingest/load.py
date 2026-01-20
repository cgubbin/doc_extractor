from dataclasses import dataclass
from pathlib import Path
import json


class PatentMeta:
    id: str
    application_number: str
    assignee: str
    filed_date: str
    grant_date: str
    inventors: list[str]
    title: str

    def __init__(self, data: dict):
        self.id = data.get("patent_number_normalised", "")
        self.application_number = data.get("application_number", "")
        self.assignee = data.get("assignee", "")
        self.filed_date = data.get("filed_date", "")
        self.grant_date = data.get("grant_date", "")
        self.inventors = data.get("inventors", [])
        self.title = data.get("title", "")


class PatentSections:
    background: str
    detailed_description: str
    summary: str

    def __init__(self, data: dict):
        self.background = data.get("background", "")
        self.detailed_description = data.get("detailed_description", "")
        self.summary = data.get("summary", "")


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
    claims: list[str]
    figure_descriptions: list[FigureDescription]
    diagnostics: dict


def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def load_processed_doc(processed_dir: str) -> PatentDocument:
    p = Path(processed_dir)
    manifest = _read_json(p / "manifest.json")
    sections = _read_json(p / manifest["artifacts"]["sections"])
    claims = _read_json(p / manifest["artifacts"]["claims"])
    figures = _read_json(p / manifest["artifacts"]["figures"])
    meta = _read_json(p / manifest["artifacts"]["metadata"])

    figure_pngs = manifest["artifacts"]["figure_pngs"]
    sheet_pngs = manifest["artifacts"]["sheet_pngs"]

    return PatentDocument(
        pdf_path=manifest["pdf_path"],
        doc_id=manifest["doc_id"],
        sha256=manifest["sha256"],
        schema_version=manifest["schema_version"],
        date_created=manifest["created_utc"],
        data_dir=str(p),
        meta=PatentMeta(meta),
        sections=PatentSections(sections),
        claims=claims,
        figure_descriptions=[FigureDescription(f) for f in figures],
        figure_pngs=figure_pngs,
        sheet_pngs=sheet_pngs,
        diagnostics=manifest.get("diagnostics", {}),
    )


def compare_patent_versions(
    submitted: PatentDocument, approved: PatentDocument, out_dir: str
) -> dict:
    out = Path(out_dir)
    meta_dir = out / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    #
    pairs, un_sub, un_app = align_claims(
        submitted.claims, approved.claims, cfg.match_threshold
    )
    diffres = diff_claims(
        submitted.claims,
        approved.claims,
        pairs,
        un_sub,
        un_app,
        cfg.unchanged_threshold,
    )

    sub_text = Path(submitted.normalized_text_path).read_text(
        encoding="utf-8", errors="replace"
    )
    app_text = Path(approved.normalized_text_path).read_text(
        encoding="utf-8", errors="replace"
    )

    sub_ex = extract_relevant_excerpts(
        sub_text,
        diffres,
        "submitted",
        cfg.excerpt_window_chars,
        cfg.max_excerpts_per_section,
    )
    app_ex = extract_relevant_excerpts(
        app_text,
        diffres,
        "approved",
        cfg.excerpt_window_chars,
        cfg.max_excerpts_per_section,
    )

    bundle = {
        "submitted_doc_id": submitted.doc_id,
        "approved_doc_id": approved.doc_id,
        "claims_diff": {
            "summary": diffres.summary,
            "alignments": [a.__dict__ for a in diffres.alignments],
            "warnings": [w.__dict__ for w in diffres.warnings],
        },
        "relevant_excerpts": {
            "submitted": [e.__dict__ for e in sub_ex],
            "approved": [e.__dict__ for e in app_ex],
        },
    }
    (meta_dir / "claims_diff.json").write_text(
        json.dumps(bundle["claims_diff"], indent=2), encoding="utf-8"
    )
    (meta_dir / "relevant_excerpts.json").write_text(
        json.dumps(bundle["relevant_excerpts"], indent=2), encoding="utf-8"
    )
    (meta_dir / "comparison_bundle.json").write_text(
        json.dumps(bundle, indent=2), encoding="utf-8"
    )
    return bundle
