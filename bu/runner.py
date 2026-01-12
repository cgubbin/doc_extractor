from __future__ import annotations
from pathlib import Path
import hashlib
import json
from datetime import datetime, timezone

from config import PipelineConfig
from models import PatentDocument, WarningItem
from extract_text import extract_text_pdftotext, normalize_text_file
from extract_figures import extract_figures
from segment import find_claims_span
from claims_parse import parse_claims
from claims_align import align_claims
from claims_diff import diff_claims
from excerpts import extract_relevant_excerpts


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def process_patent_pdf(
    pdf_path: str, out_dir: str, doc_id: str, cfg: PipelineConfig
) -> PatentDocument:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sha = _sha256_file(pdf_path)
    doc_root = out / doc_id
    text_dir = doc_root / "text"
    fig_dir = doc_root / "figures"
    meta_dir = doc_root / "meta"
    for d in (text_dir, fig_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)

    raw_txt = str(text_dir / "raw.txt")
    norm_txt = str(text_dir / "normalized.txt")

    logs = {"text": None, "figures": [], "warnings": []}

    # 1) Text extraction
    text_log = extract_text_pdftotext(pdf_path, raw_txt, cfg)
    logs["text"] = text_log
    normalize_text_file(raw_txt, norm_txt)

    normalized = Path(norm_txt).read_text(encoding="utf-8", errors="replace")
    if len(normalized.strip()) < 200:
        logs["warnings"].append(
            {
                "code": "TEXT_SHORT",
                "message": "Extracted text is very short; PDF may be scanned or extraction failed.",
            }
        )

    # 2) Figures
    figures, figure_logs = extract_figures(pdf_path, str(fig_dir), cfg)
    logs["figures"] = figure_logs

    # 3) Sectioning + claims parse
    sections = {}
    claims_span = find_claims_span(normalized)
    claims = []
    if claims_span:
        sections["claims"] = claims_span
        claims_text = normalized[claims_span.start : claims_span.end]
        claims = parse_claims(claims_text)

    warnings = []
    if not claims_span:
        warnings.append(
            WarningItem(
                code="CLAIMS_NOT_FOUND",
                message="Could not locate claims section reliably.",
            )
        )
    elif len(claims) < cfg.min_claims_expected:
        warnings.append(
            WarningItem(
                code="CLAIMS_PARSE_LOW",
                message=f"Parsed {len(claims)} claims; expected at least {cfg.min_claims_expected}.",
            )
        )

    doc = PatentDocument(
        pdf_path=pdf_path,
        doc_id=doc_id,
        sha256=sha,
        out_dir=str(doc_root),
        raw_text_path=raw_txt,
        normalized_text_path=norm_txt,
        figures=figures,
        sections=sections,
        claims=claims,
        warnings=warnings,
    )

    manifest = {
        "doc_id": doc_id,
        "pdf_path": pdf_path,
        "sha256": sha,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": cfg.__dict__,
        "logs": logs,
        "warnings": [w.__dict__ for w in warnings],
        "counts": {"figures": len(figures), "claims": len(claims)},
    }
    (meta_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # Structured outputs
    (meta_dir / "claims.json").write_text(
        json.dumps([c.__dict__ for c in claims], indent=2), encoding="utf-8"
    )
    (meta_dir / "sections.json").write_text(
        json.dumps({k: v.__dict__ for k, v in sections.items()}, indent=2),
        encoding="utf-8",
    )

    return doc


def compare_patent_versions(
    submitted: PatentDocument,
    approved: PatentDocument,
    out_dir: str,
    cfg: PipelineConfig,
) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta_dir = out / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

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
        submitted.sections,
        diffres,
        source_label="submitted",
        window_chars=cfg.excerpt_window_chars,
        max_per_section=cfg.max_excerpts_per_section,
    )
    app_ex = extract_relevant_excerpts(
        app_text,
        approved.sections,
        diffres,
        source_label="approved",
        window_chars=cfg.excerpt_window_chars,
        max_per_section=cfg.max_excerpts_per_section,
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
