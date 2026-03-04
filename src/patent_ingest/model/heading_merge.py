from __future__ import annotations

import re
from typing import List, Sequence

from doc_extractor.model.segment_para import ParagraphBlock


_ALL_CAPSISH = re.compile(r"^[^a-z]*$")  # no lowercase letters
_ENDS_SENTENCE = re.compile(r"[.!?]\s*$")


def _looks_like_heading_line(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    # Headings tend to be short-ish; keep len high enough for patents
    if len(s) > 120:
        return False
    # Many headings are caps; allow Title Case too, but penalize full sentences
    if _ENDS_SENTENCE.search(s):
        return False
    return True


def merge_multiline_headings(
    blocks: Sequence[ParagraphBlock],
    *,
    max_gap: float = 6.0,
    overlap_tol: float = 4.0,
    joiner: str = " ",
) -> List[ParagraphBlock]:
    """
    Merge consecutive section_heading blocks that form a multi-line heading.

    Preconditions:
      - blocks are in reading order (page order, col order within page)
      - heading blocks are already correctly typed as kind='section_heading'

    Returns a new list of blocks where merged heading blocks replace the originals.
    """
    out: List[ParagraphBlock] = []
    i = 0

    while i < len(blocks):
        b = blocks[i]

        if b.kind != "section_heading":
            out.append(b)
            i += 1
            continue

        # Start a merge group
        text_parts = [(b.text or "").strip()]
        y0 = b.y0
        y1 = b.y1
        page = b.page
        col = b.col

        j = i + 1
        while j < len(blocks):
            n = blocks[j]
            if n.kind != "section_heading":
                break
            if n.page != page or n.col != col:
                break

            gap = n.y0 - y1

            # NEW: accept small overlaps (gap can be slightly negative)
            if gap < -overlap_tol or gap > max_gap:
                break

            if not _looks_like_heading_line(n.text):
                break

            text_parts.append((n.text or "").strip())
            y1 = max(y1, n.y1)
            j += 1

        merged_text = joiner.join([t for t in text_parts if t]).strip()

        # emit merged block (keep page/col, extend y1, keep kind)
        out.append(
            ParagraphBlock(
                page=page,
                col=col,
                y0=y0,
                y1=y1,
                kind="section_heading",
                text=merged_text,
            )
        )

        i = j

    return out
