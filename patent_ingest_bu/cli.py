from __future__ import annotations
import argparse
from .config import PipelineConfig
from .runner import process_patent_pdf, load_processed_doc, compare_patent_versions

def main() -> int:
    ap = argparse.ArgumentParser(prog="patent-ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("process", help="Process a single patent PDF.")
    p1.add_argument("--pdf", required=True)
    p1.add_argument("--out", required=True)
    p1.add_argument("--doc-id", required=True)

    p2 = sub.add_parser("compare", help="Compare two processed documents (submitted vs approved).")
    p2.add_argument("--submitted", required=True, help="Path to processed submitted dir (contains meta/run_manifest.json)")
    p2.add_argument("--approved", required=True, help="Path to processed approved dir")
    p2.add_argument("--out", required=True)

    args = ap.parse_args()
    cfg = PipelineConfig()

    if args.cmd == "process":
        process_patent_pdf(args.pdf, args.out, args.doc_id, cfg)
        return 0
    if args.cmd == "compare":
        sub_doc = load_processed_doc(args.submitted)
        app_doc = load_processed_doc(args.approved)
        compare_patent_versions(sub_doc, app_doc, args.out, cfg)
        return 0
    return 2
