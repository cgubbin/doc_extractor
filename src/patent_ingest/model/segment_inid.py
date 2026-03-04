from __future__ import annotations

from typing import Dict, List, Optional
import re

from doc_extractor.model.model import Block, ColumnStream, Region

INID_START_RE = re.compile(r"^\(\s*(\d+)\s*\)")


def is_inid_label_line(text: str) -> bool:
    return bool(INID_START_RE.match((text or "").strip()))


def inid_num(text: str) -> Optional[int]:
    m = INID_START_RE.match((text or "").strip())
    return int(m.group(1)) if m else None


def inid_label_count(stream: ColumnStream) -> int:
    return sum(1 for ln in stream.lines if is_inid_label_line(ln.text))


def _adaptive_buffer(y0: float, y1: float, base: float, frac: float = 0.4) -> float:
    gap = max(0.0, y1 - y0)
    return min(base, gap * frac)


def segment_inid_blocks(
    stream: ColumnStream,
    *,
    region: Region,
    prefix_window: float = 90.0,
    max_span: float = 900.0,
    gap_stop: float = 70.0,
    keep_unlabelled: bool = True,
) -> List[Block]:
    """
    Segments one column into INID blocks + optional unlabelled blocks.
    Supports:
      - '(60) Provisional ...' label+value on same line
      - '(57)' label alone
    """
    lines = list(stream.lines)
    if not lines:
        return []

    # for ii, each in enumerate(lines):
    #     print(f"Line {ii}: text={each.text} is_label={is_inid_label_line(each.text)} ")
    labels = [i for i, ln in enumerate(lines) if is_inid_label_line(ln.text)]
    if not labels:
        if keep_unlabelled:
            txt = stream.join()
            if txt:
                return [
                    Block(
                        stream.col,
                        region,
                        lines[0].y0,
                        lines[-1].y1,
                        "unlabelled",
                        None,
                        txt,
                    )
                ]
        return []

    y_stop_for: Dict[int, float] = {}
    buf_for: Dict[int, float] = {}
    for pos, li in enumerate(labels):
        y0 = lines[li].y
        if pos + 1 < len(labels):
            y1 = lines[labels[pos + 1]].y
            buf = _adaptive_buffer(y0, y1, prefix_window, frac=0.4)
            buf_for[li] = buf
            y_stop_for[li] = max(y0 + 1e-3, y1 - buf)
        else:
            buf_for[li] = prefix_window
            y_stop_for[li] = y0 + max_span

    blocks: List[Block] = []
    consumed = [False] * len(lines)
    prev_end = -float("inf")

    def emit_unlabelled(start_i: int, end_i: int) -> None:
        if not keep_unlabelled or end_i <= start_i:
            return
        chunk = [lines[k] for k in range(start_i, end_i) if not consumed[k]]
        if not chunk:
            return
        txt = "\n".join(ln.text for ln in chunk if ln.text).strip()
        if not txt:
            return
        blocks.append(
            Block(
                stream.col, region, chunk[0].y0, chunk[-1].y1, "unlabelled", None, txt
            )
        )
        for k in range(start_i, end_i):
            if not consumed[k]:
                consumed[k] = True

    # INID blocks
    for li in labels:
        ln_label = lines[li]
        y_label = ln_label.y
        stop = y_stop_for[li]
        buf = buf_for[li]
        prefix_start_y = max(prev_end, y_label - buf)

        # prefix: above label within window, stop at previous label
        prefix_idx: List[int] = []
        j = li - 1
        while j >= 0:
            if lines[j].y < prefix_start_y:
                break
            if is_inid_label_line(lines[j].text):
                break
            prefix_idx.insert(0, j)
            j -= 1

        # below: until stop/next label/large gap
        below_idx: List[int] = []
        last_y = y_label
        j = li + 1
        while j < len(lines):
            if lines[j].y >= stop:
                break
            if is_inid_label_line(lines[j].text):
                break
            if (lines[j].y - last_y) > gap_stop:
                break
            below_idx.append(j)
            last_y = lines[j].y
            j += 1

        idxs = [li, *prefix_idx, *below_idx]
        for k in idxs:
            consumed[k] = True

        merged = "\n".join(lines[k].text for k in idxs if lines[k].text).strip()
        y0 = min(lines[k].y0 for k in idxs)
        y1 = max(lines[k].y1 for k in idxs)
        blocks.append(
            Block(stream.col, region, y0, y1, "inid", inid_num(ln_label.text), merged)
        )
        prev_end = stop

    # unlabelled remainder
    if keep_unlabelled:
        run_start = 0
        for i in range(len(lines) + 1):
            if i == len(lines) or consumed[i]:
                emit_unlabelled(run_start, i)
                run_start = i + 1

    blocks.sort(key=lambda b: b.y0)
    return blocks
