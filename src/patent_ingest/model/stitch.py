from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from patent_ingest.model.model import Block, Col, PageLayout
from patent_ingest.model.classify import classify_page


def _leading_non_inid_blocks(
    blocks: List[Block], *, top_y_max: float = 220.0
) -> List[Block]:
    """
    Return leading blocks (in y order) that are NOT inid blocks and appear near top of the page.
    Used as "continuation candidates" for previous page's final INID field.
    """
    out: List[Block] = []
    for b in sorted(blocks, key=lambda x: x.y0):
        if b.y0 > top_y_max:
            break
        if b.kind == "inid":
            break
        if b.text.strip():
            out.append(b)
    return out


def stitch_inid_blocks_across_pages(
    pages_blocks: List[List[Block]],
    *,
    top_y_max: float = 220.0,
) -> List[List[Block]]:
    """
    Mutates structure logically (returns new list) by appending leading non-INID text on page i+1
    to the last INID block on page i in the same column, when appropriate.

    Conservative rule:
      - For each column separately:
        If page i ends with an INID block (last in that col),
        then on page i+1, take leading non-INID blocks before first INID (within top_y_max),
        append their text to that prior INID block, and remove them from page i+1.
    """
    out_pages: List[List[Block]] = [list(bs) for bs in pages_blocks]

    last_inid_by_col: Dict[Col, Optional[Tuple[int, int]]] = {"L": None, "R": None}
    # maps col -> (page_index, block_index in out_pages[page_index])

    for p in range(len(out_pages)):
        bs = out_pages[p]
        # group by column
        by_col = {
            "L": [b for b in bs if b.col == "L"],
            "R": [b for b in bs if b.col == "R"],
        }

        # before processing this page, try to attach leading non-inid blocks to previous page's last inid
        if p > 0:
            for col in ("L", "R"):
                prev_ref = last_inid_by_col[col]
                if prev_ref is None:
                    continue

                prev_page, prev_bi = prev_ref
                prev_block = out_pages[prev_page][prev_bi]
                if prev_block.kind != "inid" or prev_block.tag is None:
                    continue

                lead = _leading_non_inid_blocks(by_col[col], top_y_max=top_y_max)
                if not lead:
                    continue

                # Append and remove those blocks from current page
                appendix = "\n".join(b.text for b in lead if b.text.strip()).strip()
                if appendix:
                    merged = (prev_block.text.rstrip() + "\n" + appendix).strip()
                    out_pages[prev_page][prev_bi] = Block(
                        col=prev_block.col,
                        region=prev_block.region,
                        y0=prev_block.y0,
                        y1=prev_block.y1,  # keep original; you can expand if you want
                        kind=prev_block.kind,
                        tag=prev_block.tag,
                        text=merged,
                    )

                # remove lead blocks from current page blocks
                lead_set = set(lead)
                out_pages[p] = [b for b in out_pages[p] if b not in lead_set]
                bs = out_pages[p]
                by_col = {
                    "L": [b for b in bs if b.col == "L"],
                    "R": [b for b in bs if b.col == "R"],
                }

        # Update last_inid_by_col based on this page AFTER removals
        for col in ("L", "R"):
            col_inids = [
                b for b in by_col[col] if b.kind == "inid" and b.tag is not None
            ]
            if not col_inids:
                continue
            # find last in document order within the page for that col
            last = max(col_inids, key=lambda b: b.y0)
            # locate its index in the page list
            idx = next(i for i, b in enumerate(out_pages[p]) if b is last)
            last_inid_by_col[col] = (p, idx)

    return out_pages


def build_inid_dict_from_pages(
    pages_blocks: List[List[Block]],
) -> Dict[int, str]:
    """
    Build doc-level INID dictionary tag->text by concatenating all INID blocks with the same tag.
    """
    out: Dict[int, List[str]] = {}
    for bs in pages_blocks:
        for b in bs:
            if b.kind != "inid" or b.tag is None:
                continue
            out.setdefault(b.tag, []).append(b.text.strip())

    # Join repeated tags with blank line separation
    return {k: "\n\n".join(v).strip() for k, v in out.items() if v}


def find_inid_cutoff_page(
    layouts: list[PageLayout],
    *,
    require_inid_start: bool = True,
) -> int:
    """
    Returns the first page index that should NOT be included in INID processing.

    Rules:
      - Start collecting once we have an INID-like page.
      - Stop permanently at the first DRAWING page (hard cut).
      - If no drawings, stop at the first BODY page.
      - If require_inid_start=True and no INID-like page found, cutoff=0.
    """
    started = False
    for i, layout in enumerate(layouts):
        pt = classify_page(layout, region="body")

        if not started:
            if pt.kind == "inid":
                started = True
            else:
                continue  # still pre-front-matter
        else:
            # hard cut requested
            if pt.kind == "drawing":
                return i
            # also stop if we’ve transitioned into prose body
            if pt.kind == "body":
                return i
