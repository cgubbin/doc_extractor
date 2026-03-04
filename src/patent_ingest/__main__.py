"""CLI entry point for doc_extractor.

Parse patent PDFs (front matter, drawings, body) and optionally export artifacts.

Examples:
    python -m doc_extractor corpus/US10935501B2.pdf --print-json
    python -m doc_extractor corpus/US10935501B2.pdf --print-canonical-front-json
    python -m doc_extractor corpus/US10935501B2.pdf --export-artifacts --export-dir out/
"""


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    from pathlib import Path

    from doc_extractor.pipeline import IngestStatus
    from doc_extractor.api import (
        FileSystemSink,
        export_artifacts,
        ExportSpec,
        parse_patent,
    )
    from doc_extractor.structured_logger import get_logger

    logger = get_logger(__name__)

    parser = argparse.ArgumentParser(
        prog="doc_extractor",
        description="Parse patent PDFs (front matter, drawings, body) and optionally export artifacts.",
    )

    # Positional
    parser.add_argument("pdf", type=Path, help="Path to patent PDF")

    # Identity / output
    parser.add_argument(
        "--doc-id",
        type=str,
        default=None,
        help="Optional document identifier (e.g., US10935501B2)",
    )

    # JSON output (stdout / files)
    parser.add_argument(
        "--print-json", action="store_true", help="Print full parsed JSON to stdout"
    )
    parser.add_argument(
        "--json", type=Path, default=None, help="Write full parsed JSON to this path"
    )
    parser.add_argument(
        "--print-canonical-front-json",
        action="store_true",
        help="Print canonical front JSON to stdout",
    )
    parser.add_argument(
        "--canonical-front-json",
        type=Path,
        default=None,
        help="Write canonical front JSON to this path",
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help="Use compact JSON formatting for --print-json/--json (canonical front is always pretty)",
    )

    # Artifact export
    parser.add_argument(
        "--export-artifacts",
        action="store_true",
        help="Export artifacts (JSON, drawing sheets, figure PNGs) into --export-dir using a filesystem sink",
    )

    parser.add_argument(
        "--export-sheet-pdfs",
        action="store_true",
        help="Export sheets as pdf files",
    )

    parser.add_argument(
        "--export-sheet-pngs",
        action="store_true",
        help="Export sheets as png files",
    )

    parser.add_argument(
        "--export-figure-pngs",
        action="store_true",
        help="Export figures as png files",
    )

    parser.add_argument(
        "--export-dir",
        type=Path,
        default=None,
        help="Directory to write exported artifacts (required if --export-artifacts is set)",
    )
    parser.add_argument(
        "--export-body-text",
        action="store_true",
        help="Export concatenated body sections text",
    )
    parser.add_argument(
        "--export-no-figures", action="store_true", help="Do not export per-figure PNGs"
    )

    # QA / exit behavior
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any QA warnings are present",
    )

    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"ERROR: PDF not found: {args.pdf}", file=sys.stderr)
        logger.error("cli_pdf_not_found", pdf_path=str(args.pdf))
        return 2

    if args.export_artifacts and args.export_dir is None:
        parser.error("--export-artifacts requires --export-dir")

    logger.info("cli_started", pdf_path=str(args.pdf), doc_id=args.doc_id)

    # ------------------------
    # Parse (pure; no exports)
    # ------------------------
    try:
        logger.info("parsing_started", pdf_path=str(args.pdf))
        result = parse_patent(pdf_path=str(args.pdf), doc_id=args.doc_id)
        logger.info(
            "parsing_completed",
            pdf_path=str(args.pdf),
            status=result.ingested.status.value,
        )
    except Exception as e:
        logger.error("parsing_exception", pdf_path=str(args.pdf), error=str(e))
        raise e

    if result.ingested.status == IngestStatus.FAILED:
        from doc_extractor.diagnostics import summarize_diagnostics

        raise RuntimeError(
            f"Patent ingest failed: {summarize_diagnostics(result.ingested.diagnostics)}"
        )

    data = result.ingested.data
    if data is None:
        raise RuntimeError("Patent ingest data empty")

    # ------------------------
    # Optional artifact export
    # ------------------------
    manifest = None
    if args.export_artifacts:
        logger.info("artifact_export_started", export_dir=str(args.export_dir))

        sink = FileSystemSink(args.export_dir)

        spec = ExportSpec(
            export_parsed_json=True,
            export_canonical_front_json=True,
            export_body_text=bool(args.export_body_text),
            export_sheet_pdfs=bool(args.export_sheet_pdfs),
            export_sheet_pngs=bool(args.export_sheet_pngs),
            export_figure_pngs=not bool(args.export_no_figures),
            include_large_fields=False,
        )

        manifest = export_artifacts(
            pdf_path=str(args.pdf),
            parse_result=result,
            sink=sink,
            spec=spec,
            doc_id=args.doc_id,
        )
        logger.info(
            "artifact_export_completed",
            export_dir=str(args.export_dir),
            files_written=len(manifest["artifacts"]) if manifest else 0,
        )

    logger.info("cli_completed", pdf_path=str(args.pdf))
    return 0
