from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from patent_ingest.pipeline import (
    OrchestratorConfig,
    ingest_patent_pdf,
    IngestionResult,
)


SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class ParseOptions:
    """Controls parsing behavior.

    Notes:
      - Parsing is best-effort; quality issues should surface via qa.warnings,
        not via exceptions (except for unrecoverable input errors).
    """

    # how many pages after page 0 to search for the first "Sheet i of n" marker
    drawings_sheet_search_limit: int = 25

    # drawing sheet exports / detection
    detect_figures: bool = True
    export_figures_png: bool = False

    # drawing sheets: export per-sheet PDF/PNG
    export_sheet_pdf: bool = False
    export_sheet_png: bool = False
    sheet_png_dpi: int = 200

    # segmentation: if True, attempt to detect individual figures in drawings
    # (drawing_sheets.process_drawing_sheets uses detect_figures + export_figures_png)
    use_opencv: bool = True


@dataclass(frozen=True)
class ExportSpec:
    """Declarative artifact export specification."""

    export_parsed_json: bool = True
    export_canonical_front_json: bool = True
    export_body_text: bool = False

    export_sheet_pdfs: bool = True
    export_sheet_pngs: bool = False
    export_figure_pngs: bool = True

    # Whether to include raw extracted evidence fields (can be large).
    include_large_fields: bool = False


@runtime_checkable
class ArtifactSink(Protocol):
    """Pluggable storage interface for generated artifacts."""

    def put_bytes(self, key: str, data: bytes, *, content_type: str) -> str:
        """Store bytes at key and return a stable URI or key."""
        ...

    def put_json(self, key: str, obj: Any) -> str:
        """Store JSON at key and return a stable URI or key."""
        ...

    def put_text(
        self, key: str, text: str, *, content_type: str = "text/plain; charset=utf-8"
    ) -> str:
        """Store UTF-8 text and return a stable URI or key."""
        ...


class FileSystemSink:
    """Default sink that writes artifacts to a local directory."""

    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path_for_key(self, key: str) -> Path:
        p = self.root_dir / key
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def put_bytes(self, key: str, data: bytes, *, content_type: str) -> str:
        p = self._path_for_key(key)
        p.write_bytes(data)
        return str(p)

    def put_json(self, key: str, obj: Any) -> str:
        p = self._path_for_key(key)
        p.write_text(
            json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return str(p)

    def put_text(
        self, key: str, text: str, *, content_type: str = "text/plain; charset=utf-8"
    ) -> str:
        p = self._path_for_key(key)
        p.write_text(text, encoding="utf-8")
        return str(p)


class MemorySink:
    """In-memory sink, useful for tests.

    Stores artifacts in dictionaries keyed by the provided key. Returns the key as the URI.
    """

    def __init__(self):
        self.blobs: dict[str, bytes] = {}
        self.json_objects: dict[str, Any] = {}
        self.texts: dict[str, str] = {}

    def put_bytes(self, key: str, data: bytes, *, content_type: str) -> str:
        self.blobs[key] = data
        return key

    def put_json(self, key: str, obj: Any) -> str:
        self.json_objects[key] = obj
        return key

    def put_text(
        self, key: str, text: str, *, content_type: str = "text/plain; charset=utf-8"
    ) -> str:
        self.texts[key] = text
        return key


def _sha256(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


@dataclass(frozen=True)
class ParseResult:
    ingested: IngestionResult
    schema_version: str
    doc_id: Optional[str]
    pdf_sha256: Optional[str]


def parse_patent(
    *,
    pdf_bytes: bytes | None = None,
    pdf_path: str | None = None,
    doc_id: str | None = None,
    options: ParseOptions | None = None,
) -> ParseResult:
    """Parse a patent PDF into structured data.

    Exactly one of pdf_bytes or pdf_path must be provided.

    Returns a JSON-serializable dict with schema_version and qa diagnostics.
    This function performs no artifact exports by default.
    """

    import logging

    # This sets the root logger to write to stdout (your console).
    # Your script/app needs to call this somewhere at least once.
    logging.basicConfig()

    # By default the root logger is set to WARNING and all loggers you define
    # inherit that value. Here we set the root logger to NOTSET. This logging
    # level is automatically inherited by all existing and new sub-loggers
    # that do not set a less verbose level.
    logging.root.setLevel(logging.NOTSET)

    # The following line sets the root logger level as well.
    # It's equivalent to both previous statements combined:
    logging.basicConfig(level=logging.NOTSET)
    if (pdf_bytes is None) == (pdf_path is None):
        raise ValueError("Provide exactly one of pdf_bytes or pdf_path.")

    options = options or ParseOptions()

    tmp_path: Optional[str] = None
    if pdf_bytes is not None:
        # Write to a temporary file to reuse the existing pipeline which expects a path.
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        Path(tmp_path).write_bytes(pdf_bytes)
        pdf_path_use = tmp_path
    else:
        pdf_path_use = str(pdf_path)

    try:
        config = OrchestratorConfig(
            export_pdf=options.export_sheet_pdf,
            export_png=options.export_sheet_png,
            segment_drawings=False,  # segmentation is controlled inside drawing_sheets by detect_figures
        )
        # Pipeline supports artifact output_dir; we pass None to keep this pure.
        result = ingest_patent_pdf(pdf_path_use, output_dir=None, config=config)

        # Add sha256 if bytes were provided (recommended for host dedupe)
        pdf_sha256: Optional[str] = None
        if pdf_bytes is not None:
            pdf_sha256 = _sha256(pdf_bytes)

        return ParseResult(result, SCHEMA_VERSION, doc_id, pdf_sha256)
    finally:
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def export_artifacts(
    *,
    pdf_bytes: bytes | None = None,
    pdf_path: str | None = None,
    parse_result: Dict[str, Any],
    sink: ArtifactSink,
    spec: ExportSpec | None = None,
    doc_id: str | None = None,
) -> Dict[str, Any]:
    """Export artifacts derived from a parse_result.

    Strategy:
      - We (re)run export steps into a temporary directory using existing modules that
        are file-system oriented.
      - Then we upload files to the sink, returning a manifest of URIs/keys.

    Note: for deterministic keys, provide doc_id (preferred) or ensure parse_result['doc_id'] exists.
    """
    if (pdf_bytes is None) == (pdf_path is None):
        raise ValueError("Provide exactly one of pdf_bytes or pdf_path.")

    spec = spec or ExportSpec()
    doc_id = (
        doc_id
        or parse_result.doc_id
        or parse_result.ingested.data.front_matter.patent_id.value
        or "unknown_doc"
    )
    diag = parse_result.ingested.diagnostics

    # Materialize PDF to a local path for export routines.
    tmp_pdf_path: Optional[str] = None
    if pdf_bytes is not None:
        fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        Path(tmp_pdf_path).write_bytes(pdf_bytes)
        pdf_path_use = tmp_pdf_path
    else:
        pdf_path_use = str(pdf_path)

    manifest: Dict[str, Any] = {"doc_id": doc_id, "artifacts": {}}

    with tempfile.TemporaryDirectory() as td:
        tmp_out = Path(td)

        if spec.export_canonical_front_json:
            canonical = parse_result.ingested.data.front_matter.canonical()
            key = f"{doc_id}/front_canonical.json"
            manifest["artifacts"]["front_canonical_json"] = sink.put_json(
                key, canonical
            )

        if spec.export_body_text:
            canonical = parse_result.ingested.data.body.canonical_sections()
            key = f"{doc_id}/body.json"
            manifest["artifacts"]["body_canonical_json"] = sink.put_json(key, canonical)
            canonical = parse_result.ingested.data.body.canonical_claims()
            key = f"{doc_id}/claims.json"
            manifest["artifacts"]["claims"] = sink.put_json(key, canonical)
            canonical = parse_result.ingested.data.body.canonical_figures()
            key = f"{doc_id}/figures.json"
            manifest["artifacts"]["figures"] = sink.put_json(key, canonical)

        # 2) Drawing sheets / figure exports
        if spec.export_sheet_pdfs or spec.export_sheet_pngs or spec.export_figure_pngs:
            print("Exporting drawing sheets and figures...")
            # To export we need to re-run drawing_sheets.process_drawing_sheets with output_dir.
            from patent_ingest.drawing_sheets.export import export_drawing_artifacts

            data = parse_result.ingested.data.drawing_sheets

            export_dir = tmp_out / "drawings"
            export_dir.mkdir(parents=True, exist_ok=True)

            export_drawing_artifacts(data, export_dir, diag)

            # Upload produced files
            for path in export_dir.rglob("*"):
                print(f"Found exported file: {path}")
                if not path.is_file():
                    continue
                rel = path.relative_to(export_dir).as_posix()
                key = f"{doc_id}/drawings/{rel}"
                ctype, _ = mimetypes.guess_type(str(path))
                ctype = ctype or "application/octet-stream"
                uri = sink.put_bytes(key, path.read_bytes(), content_type=ctype)
                # put into manifest buckets
                if rel.endswith(".pdf") and rel.startswith("sheets/"):
                    manifest["artifacts"].setdefault("sheet_pdfs", []).append(uri)
                elif rel.endswith(".png") and rel.startswith("sheets_png/"):
                    manifest["artifacts"].setdefault("sheet_pngs", []).append(uri)
                elif rel.endswith(".png") and (
                    "figures" in rel or "figures_png" in rel
                ):
                    manifest["artifacts"].setdefault("figure_pngs", []).append(uri)
                else:
                    manifest["artifacts"].setdefault("other", []).append(uri)

    if tmp_pdf_path is not None:
        try:
            os.remove(tmp_pdf_path)
        except OSError:
            pass

    return manifest
