import os
import glob
import json
from pypdf import PdfReader

from patent_ingest.parse_front_page import extract_page0_text, parse_front_page


ROOT = os.path.dirname(os.path.dirname(__file__))
CORPUS_DIR = os.path.join(ROOT, "corpus")


def main(out_jsonl: str):
    pdfs = sorted(glob.glob(os.path.join(CORPUS_DIR, "*.pdf")))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {CORPUS_DIR}")

    summary = {
        "total": 0,
        "warnings": {},
        "avg_cited_us_patents": 0.0,
    }

    cited_counts = []

    with open(out_jsonl, "w", encoding="utf-8") as f:
        for path in pdfs:
            reader = PdfReader(path)
            text0 = extract_page0_text(reader)
            parsed = parse_front_page(text0)

            cited = parsed["references_cited"]["cited_us_patents"]

            record = {
                "file": os.path.basename(path),
                "patent": parsed["patent_number"]["normalized"],
                "title": parsed["title"]["value"],
                "assignee": parsed["assignee"]["value"],
                "inventor_count": len(parsed["inventors"]["parsed"]),
                "cited_us_patent_count": len(cited),
                "warnings": parsed["qa"]["warnings"],
            }

            f.write(json.dumps(record, ensure_ascii=False) + "\n")

            cited_counts.append(len(cited))
            summary["total"] += 1
            for w in record["warnings"]:
                summary["warnings"][w] = summary["warnings"].get(w, 0) + 1

    summary["avg_cited_us_patents"] = sum(cited_counts) / len(cited_counts) if cited_counts else 0.0

    print(f"Processed {summary['total']} patents")
    print(f"Average cited US patents: {summary['avg_cited_us_patents']:.2f}")
    print("Top warnings:")
    for k, v in sorted(summary["warnings"].items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {k}: {v}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python tools/run_corpus.py <out.jsonl>")
        raise SystemExit(1)

    main(sys.argv[1])
