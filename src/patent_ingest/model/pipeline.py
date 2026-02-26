from __future__ import annotations

from typing import Dict, List
import pymupdf

from patent_ingest.model.model import Block, ColumnStream, PageLayout
from patent_ingest.model.extract import extract_column_streams
from patent_ingest.model.region import (
    split_header_body_generic,
    rescue_lines_from_header_into_body,
)
from patent_ingest.model.noise import detect_noise_cutoff_y, apply_cutoff
from patent_ingest.model.segment_inid import segment_inid_blocks, inid_label_count
from patent_ingest.model.segment_para import segment_paragraph_blocks
from patent_ingest.model.stitch import (
    build_inid_dict,
    find_inid_cutoff_page,
)


def build_page_layout(
    doc: pymupdf.Document,
    page_index: int,
    *,
    header_margin: float = 5.0,
    footer_margin: float = 5.0,
    min_split_gap: float = 22.0,
    mid_gutter: float = 10.0,
    # header split tuning
    top_frac: float = 0.22,
    max_band_height: float = 30.0,
    # running header split tuning (fallback)
    running_top_band: float = 85.0,
    running_bottom_band: float = 60.0,
) -> PageLayout:
    page = doc.load_page(page_index)
    rect = page.rect

    streams = extract_column_streams(
        page,
        header_margin=header_margin,
        footer_margin=footer_margin,
        min_split_gap=min_split_gap,
        mid_gutter=mid_gutter,
    )
    from patent_ingest.model.region import (
        choose_header_splitter,
        split_header_body_strict_metadata,
    )

    mode = choose_header_splitter(streams["L"], streams["R"], page_height=rect.height)

    if mode == "strict_metadata":
        header, body = split_header_body_strict_metadata(
            streams["L"], streams["R"], page_height=rect.height
        )
    else:
        header, body = split_header_body_generic(
            streams["L"],
            streams["R"],
            page_height=rect.height,
            top_frac=top_frac,
            max_band_height=max_band_height,
        )

    from patent_ingest.model.util import (
        split_cross_gutter_header_lines,
    )

    # 3) Repair rare cross-gutter header lines (e.g. "(12)...(10)...")

    header = split_cross_gutter_header_lines(
        header,
        page_width=rect.width,
        mid_gutter=mid_gutter,
    )

    # Optional: rescue a few lines right above (54) into body if present.
    header, body = rescue_lines_from_header_into_body(
        header, body, target_inid=54, rescue_lines=4, rescue_dy=20.0
    )

    return PageLayout(
        page_index=page_index,
        header={
            "L": ColumnStream("L", tuple(header["L"])),
            "R": ColumnStream("R", tuple(header["R"])),
        },
        body={
            "L": ColumnStream("L", tuple(body["L"])),
            "R": ColumnStream("R", tuple(body["R"])),
        },
    )


def segment_page_blocks(
    layout: PageLayout,
    *,
    is_inid_page: bool = False,
    region: str = "body",
    keep_unlabelled: bool = True,
    prefix_window: float = 90.0,
    gap_stop: float = 70.0,
    order: str = "column-major",
) -> List[Block]:
    """
    Segments a page into blocks. Column-major by default.
    If INIDs present, uses INID segmentation; otherwise paragraph segmentation.
    """

    blocks_L: List[Block] = []
    blocks_R: List[Block] = []

    for col, store in (("L", blocks_L), ("R", blocks_R)):
        stream = layout.stream(region, col)
        if is_inid_page:
            # concatenate header+body streams for this column, preserving y-order
            lines = list(layout.header[col].lines) + list(layout.body[col].lines)
            lines.sort(key=lambda ln: getattr(ln, "y0", getattr(ln, "y", 0.0)))

            # build a temporary ColumnStream-compatible object
            merged_stream = ColumnStream(col, tuple(lines))
            store.extend(
                segment_inid_blocks(
                    merged_stream,
                    region=region,
                    prefix_window=prefix_window,
                    gap_stop=gap_stop,
                    keep_unlabelled=keep_unlabelled,
                )
            )
        else:
            store.extend(segment_paragraph_blocks(stream, region=region))

    blocks_L.sort(key=lambda b: b.y0)
    blocks_R.sort(key=lambda b: b.y0)

    if order == "column-major":
        return blocks_L + blocks_R
    elif order == "row-major":
        allb = blocks_L + blocks_R
        allb.sort(key=lambda b: b.y0)
        return allb
    else:
        raise ValueError(f"Unknown order={order!r}")


def build_document_inid_dict(
    doc: pymupdf.Document,
    *,
    keep_unlabelled: bool = True,
    prefix_window: float = 90.0,
    gap_stop: float = 70.0,
) -> Dict[int, str]:
    """
    Returns a doc-level INID dictionary {54: ..., 57: ..., ...}.

    HARD STOP: INID processing ends at the first drawing sheet (or first body page),
    so INID fields do not bleed into drawings/main body.
    """
    # 1) Build layouts for all pages (cheap enough and simplifies cutoff logic)
    layouts: List[PageLayout] = [
        build_page_layout(doc, i) for i in range(doc.page_count)
    ]

    # 2) Find where INID front matter ends
    cutoff = find_inid_cutoff_page(layouts)

    if cutoff <= 0:
        return {}

    # 3) Segment blocks only for pages in [0, cutoff)
    pages_blocks: List[List[Block]] = []

    for layout in layouts[:cutoff]:
        # Apply conservative stamp/noise cutoff only on INID-like pages
        inids = inid_label_count(layout.body["L"]) + inid_label_count(layout.body["R"])
        if inids >= 3:
            cutoff_y = detect_noise_cutoff_y(
                list(layout.body["R"].lines), min_gap=70.0, min_y=200.0
            )
            if cutoff_y is not None:
                L_kept, _ = apply_cutoff(list(layout.body["L"].lines), cutoff_y)
                R_kept, _ = apply_cutoff(list(layout.body["R"].lines), cutoff_y)
                layout = PageLayout(
                    page_index=layout.page_index,
                    header=layout.header,
                    body={
                        "L": ColumnStream("L", tuple(L_kept)),
                        "R": ColumnStream("R", tuple(R_kept)),
                    },
                )

        blocks = segment_page_blocks(
            layout,
            region="body",
            keep_unlabelled=keep_unlabelled,
            prefix_window=prefix_window,
            gap_stop=gap_stop,
            order="column-major",
        )
        pages_blocks.append(blocks)

    # 4) Stitch only within front-matter window
    # stitched_pages = stitch_inid_blocks_across_pages(pages_blocks, top_y_max=220.0)

    # 5) Build final INID dict
    return build_inid_dict(pages_blocks)


if __name__ == "__main__":
    doc = pymupdf.open("/Users/kit/Repos/patent_crawler/data/pdfs/US20110054659A1.pdf")
    inids = build_document_inid_dict(doc)

    for k, v in inids.items():
        print("INID:", k, v)

    # title = inids.get(54)
    # print("Title:", title)
    # abstract = inids.get(57)
    # print("Abstract:", abstract)
    # priority = inids.get(60)
    # print("Priority:", priority)
