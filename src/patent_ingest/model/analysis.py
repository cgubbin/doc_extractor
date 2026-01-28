# patent_ingest/public_api.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Literal
import re
import pymupdf

from patent_ingest.model.pipeline import build_page_layout, segment_page_blocks
from patent_ingest.model.classify import classify_page
from patent_ingest.model.stitch import (
    find_inid_cutoff_page,
    stitch_inid_blocks_across_pages,
    build_inid_dict_from_pages,
)
from patent_ingest.model.segment_para import segment_paragraph_blocks
from patent_ingest.model.model import Block, PageLayout

PARA_NUM_RE = re.compile(r"^\s*\d{4}\s*[.\)]\s*")
HEADING_RE = re.compile(r"^[A-Z0-9][A-Z0-9\s\-:,]{3,}$")


@dataclass(frozen=True)
class InidResult:
    fields: Dict[int, str]
    pages: List[int]


@dataclass(frozen=True)
class ParagraphBlock:
    page: int
    col: Literal["L", "R"]
    y0: float
    y1: float
    kind: Literal["section_heading", "paragraph", "enumerator", "para_marker"]
    text: str


@dataclass(frozen=True)
class BodyResult:
    blocks: List[ParagraphBlock]
    pages: List[int]
    headings: List[ParagraphBlock]

    def linearize_body(self) -> str:
        # column-major already embedded because we appended L then R per page,
        # but across pages it’s in page order
        return "\n\n".join(b.text for b in self.blocks).strip()


@dataclass(frozen=True)
class DrawingResult:
    page_indices: List[int]
    count: int


@dataclass(frozen=True)
class DocumentAnalysis:
    inid: InidResult
    body: BodyResult
    drawings: DrawingResult


PARA_NUM_RE = re.compile(r"^\s*\d{4}\s*[.\)]\s*")
HEADING_LINE_RE = re.compile(r"^[A-Z0-9][A-Z0-9\s\-:,]{3,}$")  # caps-ish


def split_heading_prefix(
    text: str, *, max_heading_lines: int = 3
) -> tuple[list[str], str]:
    """
    Returns (heading_lines, remaining_text).
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], ""

    headings: list[str] = []
    i = 0
    while i < min(len(lines), max_heading_lines):
        ln = lines[i]
        # stop if it looks like a numbered paragraph start
        if PARA_NUM_RE.match(ln):
            break
        # heading line heuristic
        if len(ln) <= 80 and HEADING_LINE_RE.match(ln) and not ln.endswith("."):
            headings.append(ln)
            i += 1
            continue
        break

    if not headings:
        return [], text.strip()

    rest = "\n".join(lines[i:]).strip()
    return headings, rest


def sections_from_blocks(
    blocks: list[ParagraphBlock],
) -> dict[str, list[ParagraphBlock]]:
    sections = {}
    current = "PREAMBLE"
    sections[current] = []
    for b in blocks:
        if b.kind in (
            "section_heading",
            "subheading",
        ):  # optionally include subheading too
            current = b.text.strip()
            sections.setdefault(current, [])
        else:
            sections[current].append(b)
    return sections


def analyze_document(doc: pymupdf.Document) -> DocumentAnalysis:
    layouts: List[PageLayout] = [
        build_page_layout(doc, i) for i in range(doc.page_count)
    ]
    page_types = [classify_page(lay) for lay in layouts]

    drawing_pages = [i for i, pt in enumerate(page_types) if pt.kind == "drawing"]
    body_pages = [i for i, pt in enumerate(page_types) if pt.kind == "body"]
    # inid pages are a *window*, not just all pages classified as inid
    inid_cutoff = find_inid_cutoff_page(layouts)
    inid_pages = list(range(0, inid_cutoff))

    # ---- INIDs: segment+stitch only inside inid_pages ----
    inid_page_blocks: List[List[Block]] = []
    for i in inid_pages:
        # force INID segmentation by using segment_page_blocks (it chooses INID when inid-like)
        bs = segment_page_blocks(layouts[i], region="body", order="column-major")
        inid_page_blocks.append(bs)

    stitched = stitch_inid_blocks_across_pages(inid_page_blocks, top_y_max=220.0)
    inid_dict = build_inid_dict_from_pages(stitched)

    # ---- Body blocks: paragraph segmentation on pages classified as body ----
    body_blocks: List[ParagraphBlock] = []
    for i in body_pages:
        lay = layouts[i]
        for col in ("L", "R"):
            seg = segment_paragraph_blocks(
                lay.body[col],
                region="body",
                emit_heading_blocks=True,  # important
                subheadings_are_boundaries=True,  # as you want for section slicing
            )
            seg.sort(key=lambda b: b.y0)

            for b in seg:
                # pass through the kind from the segmenter
                # expected kinds: "section_heading", "subheading", "paragraph"
                if b.kind not in ("section_heading", "subheading", "paragraph"):
                    continue

                body_blocks.append(
                    ParagraphBlock(
                        page=i,
                        col=col,
                        y0=b.y0,
                        y1=b.y1,
                        kind=b.kind,  # <-- key change
                        text=b.text,
                    )
                )

    # for i in body_pages:
    #     lay = layouts[i]
    #     # segment per column; keep column-major semantics by emitting L then R
    #     for col in ("L", "R"):
    #         seg = segment_paragraph_blocks(lay.body[col], region="body")
    #         seg.sort(key=lambda b: b.y0)
    #         for b in seg:
    #             headings, rest = split_heading_prefix(b.text)
    #
    #             for h in headings:
    #                 body_blocks.append(
    #                     ParagraphBlock(
    #                         page=i, col=col, y0=b.y0, y1=b.y1, kind="heading", text=h
    #                     )
    #                 )
    #
    #             if rest:
    #                 body_blocks.append(
    #                     ParagraphBlock(
    #                         page=i,
    #                         col=col,
    #                         y0=b.y0,
    #                         y1=b.y1,
    #                         kind="paragraph",
    #                         text=rest,
    #                     )
    #                 )

    headings = [b for b in body_blocks if b.kind == "heading"]

    return DocumentAnalysis(
        inid=InidResult(fields=inid_dict, pages=inid_pages),
        body=BodyResult(blocks=body_blocks, pages=body_pages, headings=headings),
        drawings=DrawingResult(page_indices=drawing_pages, count=len(drawing_pages)),
    )


if __name__ == "__main__":
    doc = pymupdf.open("/Users/kit/Repos/patent_crawler/data/pdfs/US20110054659A1.pdf")
    analysis = analyze_document(doc)

    for each in analysis.inid.fields.items():
        print("INID:", each)

    print(analysis.drawings)

    for each in analysis.body.headings:
        print("Para: ", each)

    sections = sections_from_blocks(analysis.body.blocks)

    for sec, blocks in sections.items():
        print("SECTION:", sec)
        for b in blocks:
            print("  ", b)
    # print(analysis.body.pages)

    # for each in analysis.body.blocks:
    # print("Para: ", each)
