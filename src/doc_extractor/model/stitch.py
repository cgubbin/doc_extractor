from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from doc_extractor.model.model import Block, Col, PageLayout
from doc_extractor.model.classify import classify_page


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
        pt = classify_page(layout)  # , region="body")

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


def _leading_prefix_before_any_inid(
    blocks: List[Block], *, top_y_max: float = 220.0
) -> List[Block]:
    blocks_sorted = sorted(blocks, key=lambda b: (b.y0, b.col))
    out: List[Block] = []
    for b in blocks_sorted:
        if b.y0 > top_y_max:
            break
        if b.kind == "inid":
            break
        if (b.text or "").strip():
            out.append(b)
    return out


def page_has_redeclared_inids(
    blocks: List[Block], *, top_y_max: float = 220.0, min_labels: int = 2
) -> bool:
    blocks_sorted = sorted(blocks, key=lambda b: (b.y0, b.col))
    n = 0
    for b in blocks_sorted:
        if b.y0 > top_y_max:
            break
        if b.kind == "inid" and b.tag is not None:
            n += 1
            if n >= min_labels:
                return True
    return False


def page_has_top_inid(blocks: List[Block], *, top_y_max: float = 220.0) -> bool:
    blocks_sorted = sorted(blocks, key=lambda b: (b.y0, b.col))
    for b in blocks_sorted:
        if b.y0 > top_y_max:
            break
        if b.kind == "inid" and b.tag is not None:
            return True
    return False


def stitch_inid_blocks_across_pages(
    pages_blocks: List[List[Block]],
    *,
    top_y_max: float = 220.0,
    redeclare_min_labels: int = 1,
) -> List[List[Block]]:
    """
    Stitch only true spill-over continuations.
    If the next page re-declares multiple INIDs at the top, treat it as a fresh INID table page
    and do NOT stitch prefix text into the previous page's last INID.
    """
    out_pages: List[List[Block]] = [list(bs) for bs in pages_blocks]

    last_inid_by_col: Dict[Col, Optional[Tuple[int, int]]] = {"L": None, "R": None}
    last_inid_any: Optional[Tuple[int, int]] = None

    def update_last_inids(page_idx: int) -> None:
        nonlocal last_inid_any
        for bi, b in enumerate(out_pages[page_idx]):
            if b.kind == "inid" and b.tag is not None:
                last_inid_any = (page_idx, bi)
                last_inid_by_col[b.col] = (page_idx, bi)

    if out_pages:
        update_last_inids(0)

    for p in range(1, len(out_pages)):
        cur = out_pages[p]
        if not cur:
            update_last_inids(p)
            continue

        if page_has_top_inid(cur, top_y_max=top_y_max):
            print("Current page has top INID; skipping stitch", cur)
            update_last_inids(p)
            continue
        # KEY GATE: if INIDs are re-declared on this page, don't stitch across
        if page_has_redeclared_inids(
            cur, top_y_max=top_y_max, min_labels=redeclare_min_labels
        ):
            update_last_inids(p)
            continue

        prefix = _leading_prefix_before_any_inid(cur, top_y_max=top_y_max)
        if prefix:
            consumed = set()

            for b in prefix:
                target = last_inid_by_col.get(b.col) or last_inid_any
                if target is None:
                    continue

                tp, tbi = target
                tgt = out_pages[tp][tbi]
                appendix = (b.text or "").strip()
                if not appendix:
                    consumed.add(id(b))
                    continue

                merged = (tgt.text.rstrip() + "\n" + appendix).strip()
                out_pages[tp][tbi] = replace(tgt, text=merged)
                consumed.add(id(b))

            if consumed:
                out_pages[p] = [b for b in out_pages[p] if id(b) not in consumed]

        update_last_inids(p)

    return out_pages


from collections import defaultdict


def build_inid_dict(pages_blocks: List[List[Block]]) -> dict[int, str]:
    acc = defaultdict(list)
    for blocks in pages_blocks:
        for b in blocks:
            if b.kind == "inid" and b.tag is not None:
                txt = (b.text or "").strip()
                if txt:
                    acc[b.tag].append(txt)

    out = {}
    for tag, parts in acc.items():
        # optional: drop exact duplicates (common with redeclared headers)
        merged = []
        for p in parts:
            if not merged or p != merged[-1]:
                merged.append(p)
        out[tag] = "\n".join(merged).strip()
    return out
