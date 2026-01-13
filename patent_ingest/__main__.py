"""
CLI entry point for patent_ingest.

Examples:
  uv run python -m patent_ingest corpus/US10935501B2.pdf --print-json
  uv run python -m patent_ingest corpus/US10935501B2.pdf --print-canonical-front-json
  uv run python -m patent_ingest corpus/US10935501B2.pdf --canonical-front-json out/front.json
  uv run python -m patent_ingest corpus/US10935501B2.pdf --json out/result.json --canonical-front-json out/front.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from patent_ingest.pipeline import OrchestratorConfig, ingest_patent_pdf
from patent_ingest.parse_front_page import canonical_front_page


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="patent_ingest",
        description="Parse patent front matter and drawing sheets, optionally exporting artifacts and JSON.",
    )
    p.add_argument("pdf", type=Path, help="Path to patent PDF")

    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory for artifacts (optional). If omitted, no artifacts are written.",
    )
    p.add_argument(
        "--png", action="store_true", help="Export drawing sheets as PNGs (if supported)"
    )
    p.add_argument(
        "--segment",
        action="store_true",
        help="Attempt to segment individual drawings on each sheet",
    )
    p.add_argument("--no-pdf", action="store_true", help="Do not export drawing sheets as PDFs")

    # Full JSON output controls (pipeline result)
    p.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write full pipeline result JSON to this path (optional)",
    )
    p.add_argument(
        "--print-json", action="store_true", help="Print full pipeline result JSON to stdout"
    )
    p.add_argument(
        "--compact",
        action="store_true",
        help="Write full JSON in compact form (default is pretty-printed)",
    )

    # Canonical front page JSON (always pretty)
    p.add_argument(
        "--canonical-front-json",
        type=Path,
        default=None,
        help="Write canonical front-page JSON to this path (pretty-printed)",
    )
    p.add_argument(
        "--print-canonical-front-json",
        action="store_true",
        help="Print canonical front-page JSON to stdout (pretty-printed)",
    )

    # Exit behavior
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero code if any QA warnings are present",
    )

    return p


def _json_dump_kwargs(compact: bool) -> dict[str, Any]:
    if compact:
        return {"ensure_ascii": False, "separators": (",", ":"), "sort_keys": True}
    return {"ensure_ascii": False, "indent": 2, "sort_keys": True}


def _write_json(path: Path, obj: Any, *, compact: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, **_json_dump_kwargs(compact))
        f.write("\n")


def _dump_pretty(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if not args.pdf.exists():
        print(f"ERROR: PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    config = OrchestratorConfig(
        export_pdf=not args.no_pdf,
        export_png=args.png,
        segment_drawings=args.segment,
    )

    result = ingest_patent_pdf(
        args.pdf,
        output_dir=args.out,
        config=config,
    )

    # Canonical front page JSON (always pretty-printed)
    front = result.get("front_matter") or {}
    canonical_front = canonical_front_page(front)

    if args.canonical_front_json is not None:
        _write_json(args.canonical_front_json, canonical_front, compact=False)

    if args.print_canonical_front_json:
        sys.stdout.write(_dump_pretty(canonical_front))

    # Full pipeline JSON output
    if args.json is not None:
        _write_json(args.json, result, compact=args.compact)

    if args.print_json:
        json.dump(result, sys.stdout, **_json_dump_kwargs(args.compact))
        sys.stdout.write("\n")

    # Human summary (stderr so stdout JSON stays clean)
    qa = result.get("qa", {}) or {}
    warnings = list(qa.get("warnings") or [])

    print("=== Patent ingest complete ===", file=sys.stderr)
    print(f"PDF: {args.pdf}", file=sys.stderr)
    print(
        f"Front-matter pages scanned: {qa.get('info', {}).get('front_matter_pages_scanned')}",
        file=sys.stderr,
    )

    expected = front.get("drawing_sheets_expected") or (result.get("front_matter", {}) or {}).get(
        "drawing_sheets_expected"
    )
    if expected is not None:
        print(f"Expected drawing sheets: {expected}", file=sys.stderr)

    ds = result.get("drawing_sheets", {}) or {}
    if "sheet_count" in ds:
        print(f"Extracted drawing sheets: {ds.get('sheet_count')}", file=sys.stderr)

    if warnings:
        print("\nWarnings:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)

    if args.strict and warnings:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
