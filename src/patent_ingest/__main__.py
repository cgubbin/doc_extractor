# CLI entry point for patent_ingest.
#
# Examples:
#   uv run python -m patent_ingest corpus/US10935501B2.pdf --print-json
#   uv run python -m patent_ingest corpus/US10935501B2.pdf --print-canonical-front-json
#   uv run python -m patent_ingest corpus/US10935501B2.pdf --canonical-front-json out/front.json
#   uv run python -m patent_ingest corpus/US10935501B2.pdf --json out/result.json --canonical-front-json out/front.json
# """
#
# from __future__ import annotations
#
# import argparse
# import json
# import sys
# from pathlib import Path
# from typing import Any
#
# from patent_ingest.pipeline import OrchestratorConfig, ingest_patent_pdf
# from patent_ingest.api import export_artifacts, ExportSpec, FileSystemSink
# from patent_ingest.parse_front_page import canonical_front_page
#
#
# def build_arg_parser() -> argparse.ArgumentParser:
#     p = argparse.ArgumentParser(
#         prog="patent_ingest",
#         description="Parse patent front matter and drawing sheets, optionally exporting artifacts and JSON.",
#     )
#     p.add_argument("pdf", type=Path, help="Path to patent PDF")
#
#     p.add_argument(
#         "--doc-id",
#         type=str,
#         default=None,
#         help="Optional document identifier to stamp into outputs (e.g., US10935501B2)",
#     )
#
#     p.add_argument(
#         "--out",
#         type=Path,
#         default=None,
#         help="Output directory for artifacts (optional). If omitted, no artifacts are written.",
#     )
#     p.add_argument(
#         "--png",
#         action="store_true",
#         help="Export drawing sheets as PNGs (if supported)",
#     )
#     p.add_argument(
#         "--segment",
#         action="store_true",
#         help="Attempt to segment individual drawings on each sheet",
#     )
#     p.add_argument(
#         "--no-pdf", action="store_true", help="Do not export drawing sheets as PDFs"
#     )
#
#     # Full JSON output controls (pipeline result)
#     p.add_argument(
#         "--json",
#         type=Path,
#         default=None,
#         help="Write full pipeline result JSON to this path (optional)",
#     )
#     p.add_argument(
#         "--print-json",
#         action="store_true",
#         help="Print full pipeline result JSON to stdout",
#     )
#     p.add_argument(
#         "--compact",
#         action="store_true",
#         help="Write full JSON in compact form (default is pretty-printed)",
#     )
#
#     # Canonical front page JSON (always pretty)
#     p.add_argument(
#         "--canonical-front-json",
#         type=Path,
#         default=None,
#         help="Write canonical front-page JSON to this path (pretty-printed)",
#     )
#     p.add_argument(
#         "--print-canonical-front-json",
#         action="store_true",
#         help="Print canonical front-page JSON to stdout (pretty-printed)",
#     )
#
#     # Exit behavior
#     p.add_argument(
#         "--strict",
#         action="store_true",
#         help="Exit with non-zero code if any QA warnings are present",
#     )
#
#     p.add_argument(
#         "--export-artifacts",
#         action="store_true",
#         help="Export artifacts (drawings, figures, JSON) via a filesystem sink",
#     )
#
#     p.add_argument(
#         "--export-dir",
#         type=Path,
#         default=None,
#         help="Directory to write exported artifacts (required if --export-artifacts is set)",
#     )
#
#     p.add_argument(
#         "--export-body-text",
#         action="store_true",
#         help="Export concatenated body sections text",
#     )
#
#     p.add_argument(
#         "--export-no-figures",
#         action="store_true",
#         help="Disable exporting figure PNGs",
#     )
#
#     return p
#
#
# def _json_dump_kwargs(compact: bool) -> dict[str, Any]:
#     if compact:
#         return {"ensure_ascii": False, "separators": (",", ":"), "sort_keys": True}
#     return {"ensure_ascii": False, "indent": 2, "sort_keys": True}
#
#
# def _write_json(path: Path, obj: Any, *, compact: bool) -> None:
#     path.parent.mkdir(parents=True, exist_ok=True)
#     with path.open("w", encoding="utf-8") as f:
#         json.dump(obj, f, **_json_dump_kwargs(compact))
#         f.write("\n")
#
#
# def _dump_pretty(obj: Any) -> str:
#     return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
#
#
# def main(argv: list[str] | None = None) -> int:
#     args = build_arg_parser().parse_args(argv)
#
#     if not args.pdf.exists():
#         print(f"ERROR: PDF not found: {args.pdf}", file=sys.stderr)
#         return 2
#
#     config = OrchestratorConfig(
#         export_pdf=not args.no_pdf,
#         export_png=args.png,
#         segment_drawings=args.segment,
#     )
#
#     result = ingest_patent_pdf(
#         args.pdf,
#         output_dir=args.out,
#         config=config,
#     )
#
#     # Optional: library-style artifact export (explicit)
#     if args.export_artifacts:
#         # if args.export_dir is None:
#         #     parser.error("--export-artifacts requires --export-dir")
#         export_root = args.export_dir or args.out
#         if export_root is None:
#             print(
#                 "ERROR: --export-artifacts requires --export-dir or --out",
#                 file=sys.stderr,
#             )
#             return 2
#
#         sink = FileSystemSink(export_root)
#         spec = ExportSpec(
#             export_parsed_json=True,
#             export_canonical_front_json=True,
#             export_body_text=bool(args.export_body_text),
#             export_sheet_pdfs=not args.no_pdf,
#             export_sheet_pngs=bool(args.png),
#             export_figure_pngs=not args.export_no_figures,
#         )
#         manifest = export_artifacts(
#             pdf_path=str(args.pdf),
#             parse_result=result,
#             sink=sink,
#             spec=spec,
#             doc_id=getattr(args, "doc_id", None)
#             or result.get("doc_id")
#             or args.pdf.stem,
#         )
#         # Write manifest alongside exports for convenience
#         try:
#             (Path(export_root) / "manifest.json").write_text(
#                 json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
#                 + "\n",
#                 encoding="utf-8",
#             )
#         except Exception:
#             pass
#
#         # Canonical front page JSON (always pretty-printed)
#         front = result.get("front_matter") or {}
#         canonical_front = canonical_front_page(front)
#
#         if args.canonical_front_json is not None:
#             _write_json(args.canonical_front_json, canonical_front, compact=False)
#
#         if args.print_canonical_front_json:
#             sys.stdout.write(_dump_pretty(canonical_front))
#
#         # Full pipeline JSON output
#         if args.json is not None:
#             _write_json(args.json, result, compact=args.compact)
#
#         if args.print_json:
#             json.dump(result, sys.stdout, **_json_dump_kwargs(args.compact))
#             sys.stdout.write("\n")
#
#         # Human summary (stderr so stdout JSON stays clean)
#         qa = result.get("qa", {}) or {}
#         warnings = list(qa.get("warnings") or [])
#
#         print("=== Patent ingest complete ===", file=sys.stderr)
#         print(f"PDF: {args.pdf}", file=sys.stderr)
#         print(
#             f"Front-matter pages scanned: {qa.get('info', {}).get('front_matter_pages_scanned')}",
#             file=sys.stderr,
#         )
#
#         expected = front.get("drawing_sheets_expected") or (
#             result.get("front_matter", {}) or {}
#         ).get("drawing_sheets_expected")
#         if expected is not None:
#             print(f"Expected drawing sheets: {expected}", file=sys.stderr)
#
#         ds = result.get("drawing_sheets", {}) or {}
#         if "sheet_count" in ds:
#             print(f"Extracted drawing sheets: {ds.get('sheet_count')}", file=sys.stderr)
#
#         if warnings:
#             print("\nWarnings:", file=sys.stderr)
#             for w in warnings:
#                 print(f"  - {w}", file=sys.stderr)
#
#         if args.strict and warnings:
#             return 1
#
#         return 0
#
#
# if __name__ == "__main__":
#     raise SystemExit(main())


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys
    from pathlib import Path
    import json

    from patent_ingest.pipeline import IngestStatus
    from patent_ingest.api import (
        FileSystemSink,
        export_artifacts,
        ExportSpec,
        parse_patent,
    )

    parser = argparse.ArgumentParser(
        prog="patent_ingest",
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
        return 2

    if args.export_artifacts and args.export_dir is None:
        parser.error("--export-artifacts requires --export-dir")

    # ------------------------
    # Parse (pure; no exports)
    # ------------------------
    try:
        result = parse_patent(pdf_path=str(args.pdf), doc_id=args.doc_id)
    except Exception as e:
        raise e

    if result.ingested.status == IngestStatus.FAILED:
        raise RuntimeError(f"Patent ingest failed: {result.error_message}")

    data = result.ingested.data
    if data is None:
        raise RuntimeError("Patent ingest data empty")

    # ------------------------
    # Canonical front JSON
    # ------------------------
    # front = data.front_matter
    # canonical = front.canonical()
    # #
    # if args.canonical_front_json is not None:
    #     args.canonical_front_json.parent.mkdir(parents=True, exist_ok=True)
    #     args.canonical_front_json.write_text(
    #         json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    #         encoding="utf-8",
    #     )
    # #
    # if args.print_canonical_front_json:
    #     sys.stdout.write(
    #         json.dumps(canonical, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    #     )
    #
    # # ------------------------
    # # Full parsed JSON
    # # ------------------------
    # dump_kwargs = (
    #     {"ensure_ascii": False, "separators": (",", ":"), "sort_keys": True}
    #     if args.compact
    #     else {"ensure_ascii": False, "indent": 2, "sort_keys": True}
    # )
    #
    # if args.json is not None:
    #     args.json.parent.mkdir(parents=True, exist_ok=True)
    #     args.json.write_text(json.dumps(result, **dump_kwargs) + "\n", encoding="utf-8")
    #
    # if args.print_json:
    #     sys.stdout.write(json.dumps(result, **dump_kwargs) + "\n")
    #
    # ------------------------
    # Optional artifact export
    # ------------------------
    manifest = None
    if args.export_artifacts:
        print("=== Exporting artifacts ===", file=sys.stderr)
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

        # Write a manifest.json for convenience
        manifest_path = Path(args.export_dir) / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # ------------------------
    # Human summary (stderr)
    # ------------------------
    # qa = result.get("qa") or {}
    # warnings = list(qa.get("warnings") or [])
    #
    # print("=== Patent ingest complete ===", file=sys.stderr)
    # print(f"PDF: {args.pdf}", file=sys.stderr)
    # if args.doc_id:
    #     print(f"Doc ID: {args.doc_id}", file=sys.stderr)
    #
    # # Try to print boundary info if available
    # qa_info = qa.get("info") or {}
    # if "drawings_start_index" in qa_info:
    #     print(
    #         f"Drawings start index: {qa_info.get('drawings_start_index')}",
    #         file=sys.stderr,
    #     )
    # if "body_start_index" in qa_info:
    #     print(f"Body start index: {qa_info.get('body_start_index')}", file=sys.stderr)
    #
    # if warnings:
    #     print("\nWarnings:", file=sys.stderr)
    #     for w in warnings:
    #         print(f"  - {w}", file=sys.stderr)
    #
    # if manifest is not None:
    #     print(f"\nArtifacts exported to: {args.export_dir}", file=sys.stderr)
    #     print("Manifest: manifest.json", file=sys.stderr)
    #
    # if args.strict and warnings:
    #     return 1
    #
    return 0
