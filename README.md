# patent_ingest

A Python library for parsing USPTO-style granted patent PDFs into structured data:
- Front matter (INID fields, abstract, cited references)
- Drawing sheets (sheet count verification, optional per-figure detection + crops)
- Patent body (sections, claims, figure references)
- Assembly layer that cross-checks consistency (claims vs front matter, figures vs drawings)

## Installation

This repository follows the `src/` layout. Install in editable mode from the repo root:

```bash
uv pip install -e .
```

## Library API (recommended integration)

The module is designed to be embedded in a larger system that downloads patents and manages storage.

### Parse-only (no side effects)

```python
from patent_ingest import parse_patent, ParseOptions

result = parse_patent(pdf_path="US10935501B2.pdf", doc_id="US10935501B2")
# result is JSON-serializable and includes qa warnings/info
```

You may also pass bytes:

```python
pdf_bytes = open("US10935501B2.pdf", "rb").read()
result = parse_patent(pdf_bytes=pdf_bytes, doc_id="US10935501B2")
```

### Artifact export (explicit)

Parsing does not write artifacts by default. To export (sheet PDFs, figure PNGs, JSON), call `export_artifacts`
with a sink.

```python
from patent_ingest.api import export_artifacts, FileSystemSink, ExportSpec

sink = FileSystemSink("out_artifacts")
spec = ExportSpec(export_parsed_json=True, export_sheet_pdfs=True, export_figure_pngs=True)

manifest = export_artifacts(
    pdf_path="US10935501B2.pdf",
    parse_result=result,
    sink=sink,
    spec=spec,
    doc_id="US10935501B2",
)
print(manifest)
```

To integrate with S3/GCS, implement the `ArtifactSink` protocol:
- `put_bytes(key, data, content_type) -> uri`
- `put_json(key, obj) -> uri`
- `put_text(key, text) -> uri`

## CLI (development convenience)

The package includes a CLI under `python -m patent_ingest` (see `src/patent_ingest/__main__.py`).
The CLI prints summaries to stderr and can emit JSON to stdout.

## Output schema and QA

`parse_patent()` returns a JSON-serializable dict that includes:

- `schema_version`
- `front_matter`
- `drawing_sheets` (and/or `drawings`)
- `patent_body`
- `qa`: `{warnings: [...], info: {...}}`

QA is best-effort and is intended for batch processing:
- Exceptions are reserved for unrecoverable errors (invalid input PDF).
- Quality/consistency issues are surfaced as `qa.warnings` with machine-readable `qa.info`.

## Project layout

```
src/patent_ingest/
  api.py                 # library-grade parse + export APIs
  pipeline.py            # orchestration
  parse_front_page.py    # front matter extraction
  drawing_sheets.py      # drawing sheets + figure detection
  parse_body.py          # body sections, claims, figure references
  assembler.py           # cross-checks and unified output
  utils.py, two_column.py
```

## Versioning

The parse output includes `schema_version` (currently `1.0.0`). Backward incompatible schema changes
should bump the major version.


## Testing helpers

- `MemorySink` is provided for unit tests; it stores artifacts in memory and returns keys.


## JSON Schemas

JSON schema files are included under `src/patent_ingest/schemas/` for:
- `parse_result.schema.json`
- `artifact_manifest.schema.json`
