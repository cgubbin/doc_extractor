from __future__ import annotations
from pathlib import Path
import hashlib, json
from datetime import datetime, timezone

from .config import PipelineConfig
from .models import PatentDocument, WarningItem
from .extract_text import extract_text_pdftotext, normalize_text_file
from .render_pages import render_pages_to_jpg
from .figure_select import select_figure_pages
from .segment import find_claims_span
from .claims_parse import parse_claims
from .claims_align import align_claims
from .claims_diff import diff_claims
from .excerpts import extract_relevant_excerpts

def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def process_patent_pdf(pdf_path: str, out_dir: str, doc_id: str, cfg: PipelineConfig) -> PatentDocument:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sha = _sha256_file(pdf_path)
    doc_root = out / doc_id
    text_dir = doc_root / "text"
    pages_dir = doc_root / "figures" / "pages"
    selected_dir = doc_root / "figures" / "selected"
    meta_dir = doc_root / "meta"
    for d in (text_dir, pages_dir, selected_dir, meta_dir):
        d.mkdir(parents=True, exist_ok=True)

    raw_txt = str(text_dir / "raw.txt")
    norm_txt = str(text_dir / "normalized.txt")

    logs = {"text": None, "render_pages": None, "figure_select": None, "warnings": []}

    # Text extraction
    logs["text"] = extract_text_pdftotext(pdf_path, raw_txt, cfg)
    normalize_text_file(raw_txt, norm_txt)
    normalized = Path(norm_txt).read_text(encoding="utf-8", errors="replace")
    if len(normalized.strip()) < 200:
        logs["warnings"].append({"code": "TEXT_SHORT", "message": "Extracted text is very short; OCR may be needed."})

    # Render pages to JPG (guaranteed)
    rendered_pages, rlog = render_pages_to_jpg(pdf_path, str(pages_dir), cfg)
    logs["render_pages"] = rlog

    # Select figure-like pages
    try:
        from PIL import Image  # ensure pillow import early to fail clearly
        fig_assets = select_figure_pages(rendered_pages, str(selected_dir), cfg)
        logs["figure_select"] = {"selected": len(fig_assets), "paths": [f.path for f in fig_assets]}
    except Exception as e:
        fig_assets = []
        logs["figure_select"] = {"error": str(e)}
        logs["warnings"].append({"code": "FIGURE_SELECT_FAILED", "message": str(e)})

    # Sectioning + claims
    sections = {}
    claims = []
    span = find_claims_span(normalized)
    if span:
        sections["claims"] = span
        claims_text = normalized[span.start:span.end]
        claims = parse_claims(claims_text)

    warnings = []
    if not span:
        warnings.append(WarningItem(code="CLAIMS_NOT_FOUND", message="Could not locate claims section reliably."))
    elif len(claims) < cfg.min_claims_expected:
        warnings.append(WarningItem(code="CLAIMS_PARSE_LOW", message=f"Parsed {len(claims)} claims; expected at least {cfg.min_claims_expected}."))

    doc = PatentDocument(
        pdf_path=pdf_path,
        doc_id=doc_id,
        sha256=sha,
        out_dir=str(doc_root),
        raw_text_path=raw_txt,
        normalized_text_path=norm_txt,
        figures_pages_dir=str(pages_dir),
        figures_selected_dir=str(selected_dir),
        sections=sections,
        claims=claims,
        warnings=warnings,
    )

    # Write structured outputs
    (meta_dir / "claims.json").write_text(json.dumps([c.__dict__ for c in claims], indent=2), encoding="utf-8")
    (meta_dir / "sections.json").write_text(json.dumps({k: v.__dict__ for k, v in sections.items()}, indent=2), encoding="utf-8")
    (meta_dir / "figures_selected.json").write_text(json.dumps([f.__dict__ for f in fig_assets], indent=2), encoding="utf-8")

    manifest = {
        "doc_id": doc_id,
        "pdf_path": pdf_path,
        "sha256": sha,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": cfg.__dict__,
        "logs": logs,
        "warnings": [w.__dict__ for w in warnings],
        "counts": {"rendered_pages": len(rendered_pages), "selected_fig_pages": len(fig_assets), "claims": len(claims)},
    }
    (meta_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return doc

def load_processed_doc(processed_dir: str) -> PatentDocument:
    p = Path(processed_dir)
    meta = json.loads((p / "meta" / "run_manifest.json").read_text(encoding="utf-8"))
    claims = json.loads((p / "meta" / "claims.json").read_text(encoding="utf-8"))
    sections = json.loads((p / "meta" / "sections.json").read_text(encoding="utf-8"))

    from .models import Claim, SectionSpan, PatentDocument, WarningItem
    return PatentDocument(
        pdf_path=meta["pdf_path"],
        doc_id=meta["doc_id"],
        sha256=meta["sha256"],
        out_dir=str(p),
        raw_text_path=str(p / "text" / "raw.txt"),
        normalized_text_path=str(p / "text" / "normalized.txt"),
        figures_pages_dir=str(p / "figures" / "pages"),
        figures_selected_dir=str(p / "figures" / "selected"),
        sections={k: SectionSpan(**v) for k, v in sections.items()},
        claims=[Claim(**c) for c in claims],
        warnings=[WarningItem(**w) for w in meta.get("warnings", [])],
    )

def compare_patent_versions(submitted: PatentDocument, approved: PatentDocument, out_dir: str, cfg: PipelineConfig) -> dict:
    out = Path(out_dir)
    meta_dir = out / "meta"
    meta_dir.mkdir(parents=True, exist_ok=True)

    pairs, un_sub, un_app = align_claims(submitted.claims, approved.claims, cfg.match_threshold)
    diffres = diff_claims(submitted.claims, approved.claims, pairs, un_sub, un_app, cfg.unchanged_threshold)

    sub_text = Path(submitted.normalized_text_path).read_text(encoding="utf-8", errors="replace")
    app_text = Path(approved.normalized_text_path).read_text(encoding="utf-8", errors="replace")

    sub_ex = extract_relevant_excerpts(sub_text, diffres, "submitted", cfg.excerpt_window_chars, cfg.max_excerpts_per_section)
    app_ex = extract_relevant_excerpts(app_text, diffres, "approved", cfg.excerpt_window_chars, cfg.max_excerpts_per_section)

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
    (meta_dir / "claims_diff.json").write_text(json.dumps(bundle["claims_diff"], indent=2), encoding="utf-8")
    (meta_dir / "relevant_excerpts.json").write_text(json.dumps(bundle["relevant_excerpts"], indent=2), encoding="utf-8")
    (meta_dir / "comparison_bundle.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return bundle
