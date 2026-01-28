from dataclasses import dataclass
import re
import pymupdf
from typing import Optional, List, Tuple


@dataclass(frozen=True)
class TwoColRow:
    y: float
    left: str = ""
    right: str = ""
    left_x0: Optional[float] = None
    right_x0: Optional[float] = None


INID_TOKEN_RE = re.compile(r"\(\s*\d+\s*\)")


# def contains_inid(text: str) -> bool:
#     return bool(INID_TOKEN_RE.search(text or ""))
INID_START_RE = re.compile(r"^\(\s*\d+\s*\)")
INID_ANY_RE = re.compile(r"\(\s*\d+\s*\)")


import re

INID_START_RE = re.compile(r"^\(\s*(\d+)\s*\)")
INID_PURE_RE = re.compile(r"^\(\s*(\d+)\s*\)$")


def is_label_line(text: str) -> bool:
    t = (text or "").strip()
    return bool(INID_START_RE.match(t)) or bool(INID_PURE_RE.match(t))


def label_num(text: str) -> int | None:
    t = (text or "").strip()
    m = INID_START_RE.match(t) or INID_PURE_RE.match(t)
    return int(m.group(1)) if m else None


def adaptive_buffer(y0: float, y1: float, base: float, frac: float = 0.4) -> float:
    gap = max(0.0, y1 - y0)
    return min(base, gap * frac)


def bind_inid_blocks_in_stream(
    stream: List[Tuple[float, str]],
    *,
    prefix_window: float = 90.0,
    max_span: float = 800.0,
    gap_stop: float = 60.0,  # if there's a giant vertical gap inside a block, stop
) -> List[Tuple[float, str]]:
    """
    Bind INID blocks within one column stream.

    Handles:
      - '(60) Provisional ...' style (label+value on same line)
      - '(57)' style pure label line, followed by 'ABSTRACT' and body lines
      - stops block early on large vertical gaps (filters stamp/noise at bottom)
    """
    stream = [
        (y, (t or "").strip())
        for y, t in sorted(stream, key=lambda x: x[0])
        if (t or "").strip()
    ]
    if not stream:
        return []

    labels = [i for i, (_, t) in enumerate(stream) if is_label_line(t)]
    if not labels:
        return stream

    # y_stop per label using next label and adaptive buffer
    y_stop = {}
    buf_for = {}
    for pos, li in enumerate(labels):
        y0 = stream[li][0]
        if pos + 1 < len(labels):
            y1 = stream[labels[pos + 1]][0]
            buf = adaptive_buffer(y0, y1, prefix_window, frac=0.4)
            buf_for[li] = buf
            stop = max(y0 + 1e-3, y1 - buf)
        else:
            buf_for[li] = prefix_window
            stop = y0 + max_span
        y_stop[li] = stop

    bound: List[Tuple[float, str]] = []
    prev_end = -float("inf")

    for pos, li in enumerate(labels):
        y_label, label_line = stream[li]
        stop = y_stop[li]
        buf = buf_for[li]
        prefix_start = max(prev_end, y_label - buf)

        # prefix lines above label (non-label only)
        prefix_lines: List[str] = []
        j = li - 1
        while j >= 0:
            yj, tj = stream[j]
            if yj < prefix_start:
                break
            if is_label_line(tj):
                break
            prefix_lines.insert(0, tj)
            j -= 1

        # below lines until stop or next label; stop on large vertical gaps (noise)
        below_lines: List[str] = []
        last_y = y_label
        for j in range(li + 1, len(stream)):
            yj, tj = stream[j]
            if yj >= stop:
                break
            if is_label_line(tj):
                break
            # gap-stop: if the block text jumps far down, it's probably a new zone/noise
            if (yj - last_y) > gap_stop:
                break
            below_lines.append(tj)
            last_y = yj

        merged = "\n".join([label_line, *prefix_lines, *below_lines]).strip()
        bound.append((y_label, merged))
        prev_end = stop

    return bound


# def is_label_line(text: str) -> bool:
#     """
#     Treat as a label if it begins with an INID token.
#     This catches '(60) Provisional ...' etc.
#     """
#     t = (text or "").strip()
#     return bool(INID_START_RE.match(t))
#
#
# def strip_leading_inid(text: str) -> str:
#     """
#     Remove the leading INID token from a label line, leaving the remainder.
#     """
#     t = (text or "").strip()
#     return INID_START_RE.sub("", t, count=1).strip()
#
#
# def is_pure_inid_line(text: str) -> bool:
#     """
#     True if the line contains ONLY one or more INID tokens (possibly separated by whitespace/newlines).
#     """
# t = (text or "").strip()
# if not t:
#     return False
# stripped = INID_TOKEN_RE.sub("", t)
# return stripped.strip() == ""


def column_stream(rows: List["TwoColRow"], col: str) -> List[Tuple[float, str]]:
    out = []
    for r in sorted(rows, key=lambda r: r.y):
        txt = (r.left if col == "L" else r.right) or ""
        txt = txt.strip()
        if txt:
            out.append((r.y, txt))
    return out


INID_TOKEN_RE = re.compile(r"\(\s*\d+\s*\)")
INID_PURE_RE = re.compile(r"^\(\s*\d+\s*\)$")


def contains_inid_digits(text: str) -> bool:
    # digits-only INID like (54); won't match (US)
    return bool(INID_TOKEN_RE.search(text or ""))


# def adaptive_buffer(y0: float, y1: float, base: float, frac: float = 0.4) -> float:
#     gap = max(0.0, y1 - y0)
#     return min(base, gap * frac)
#
#
# def bind_inid_blocks_in_stream(
#     stream: List[Tuple[float, str]],
#     *,
#     prefix_window: float = 90.0,
#     max_span: float = 600.0,
# ) -> List[Tuple[float, str]]:
#     stream = [
#         (y, (t or "").strip())
#         for y, t in sorted(stream, key=lambda x: x[0])
#         if (t or "").strip()
#     ]
#     if not stream:
#         return []
#
#     labels = [i for i, (_, t) in enumerate(stream) if is_label_line(t)]
#     if not labels:
#         return stream
#
#     # adaptive stops
#     y_stop = {}
#     buf_for = {}
#     for pos, li in enumerate(labels):
#         y0 = stream[li][0]
#         if pos + 1 < len(labels):
#             y1 = stream[labels[pos + 1]][0]
#             buf = adaptive_buffer(y0, y1, prefix_window, frac=0.4)
#             buf_for[li] = buf
#             stop = max(y0 + 1e-3, y1 - buf)
#         else:
#             buf_for[li] = prefix_window
#             stop = y0 + max_span
#         y_stop[li] = stop
#
#     bound: List[Tuple[float, str]] = []
#     prev_end = -float("inf")
#
# for pos, li in enumerate(labels):
#     y_label, label_line = stream[li]
#     stop = y_stop[li]
#     buf = buf_for[li]
#     prefix_start = max(prev_end, y_label - buf)
#
#     # prefix: collect non-label lines above within prefix window
#     prefix_lines: List[str] = []
#     j = li - 1
#     while j >= 0:
#         yj, tj = stream[j]
#         if yj < prefix_start:
#             break
#         if is_label_line(tj):  # <-- important: stop at earlier label lines
#             break
#         prefix_lines.insert(0, tj)
#         j -= 1
#
#     # below: collect until stop or next label line
#     below_lines: List[str] = []
#     for j in range(li + 1, len(stream)):
#         yj, tj = stream[j]
#         if yj >= stop:
#             break
#         if is_label_line(tj):  # <-- important: stop at next label line
#             break
#         below_lines.append(tj)
#
#     merged = "\n".join([label_line, *prefix_lines, *below_lines]).strip()
#     bound.append((y_label, merged))
#     prev_end = stop
#
# return bound
#

# def bind_inid_blocks_in_stream(
#     stream: List[Tuple[float, str]],
#     *,
#     prefix_window: float = 90.0,  # how far above a label its content may appear
#     max_span: float = 600.0,  # cap for last label
# ) -> List[Tuple[float, str]]:
#     """
#     Bind INID blocks within ONE physical column stream.
#
#     Key properties:
#     - Uses SAME-column next-label boundaries (since this is already a per-column stream).
#     - Captures prefix lines above each label in a protected window.
#     - No overlap: prefix capture for label k starts no earlier than end of label k-1.
#     """
#
#     # normalize
#     stream = [
#         (y, (t or "").strip())
#         for y, t in sorted(stream, key=lambda x: x[0])
#         if (t or "").strip()
#     ]
#     if not stream:
#         return []
#
#     # label indices in this stream
#     labels = [i for i, (_, t) in enumerate(stream) if is_label_line(t)]
#     if not labels:
#         return stream
#
#     # Precompute per-label y_stop (end of this label's "below" segment)
#     y_stop = {}
#     buf_for = {}
#     for pos, li in enumerate(labels):
#         y0 = stream[li][0]
#         if pos + 1 < len(labels):
#             y1 = stream[labels[pos + 1]][0]
#             buf = adaptive_buffer(y0, y1, prefix_window, frac=0.4)
#             buf_for[li] = buf
#             stop = max(y0 + 1e-3, y1 - buf)  # ensure stop after y0
#         else:
#             buf_for[li] = prefix_window
#             stop = y0 + max_span
#         y_stop[li] = stop
#
#     bound: List[Tuple[float, str]] = []
#
#     prev_end = -float("inf")
#
#     for pos, li in enumerate(labels):
#         y_label, label_text = stream[li]
#         stop = y_stop[li]
#         # How far up we’re allowed to look for prefix content for THIS label
#         buf = buf_for[li]
#         prefix_start = max(prev_end, y_label - buf)
#
#         # Collect prefix lines in [prefix_start, y_label), skipping INID tokens
#         prefix_lines: List[str] = []
#         j = li - 1
#         while j >= 0:
#             yj, tj = stream[j]
#             if yj < prefix_start:
#                 break
#             if is_label_line(tj):
#                 break
#             if contains_inid_digits(tj):
#                 j -= 1
#                 continue
#             prefix_lines.insert(0, tj)
#             j -= 1
#
#         # Collect below lines in (y_label, stop), skipping INID tokens
#         below_lines: List[str] = []
#         for j in range(li + 1, len(stream)):
#             yj, tj = stream[j]
#             if yj >= stop:
#                 break
#             if is_label_line(tj):
#                 break
#             if contains_inid_digits(tj):
#                 continue
#             below_lines.append(tj)
#
#         merged = "\n".join([label_text, *prefix_lines, *below_lines]).strip()
#         bound.append((y_label, merged))
#
#         # Next block is not allowed to steal from before this stop
#         prev_end = stop
#
#     return bound
#


def merge_bound_streams_to_rows(
    left_bound: List[Tuple[float, str]],
    right_bound: List[Tuple[float, str]],
) -> List["TwoColRow"]:
    # each bound item becomes a row with content in its column
    rows = []
    for y, t in left_bound:
        rows.append(TwoColRow(y=y, left=t, right="", left_x0=None, right_x0=None))
    for y, t in right_bound:
        rows.append(TwoColRow(y=y, left="", right=t, left_x0=None, right_x0=None))
    return sorted(rows, key=lambda r: r.y)


INID_RE = re.compile(r"^\(\s*(\d+)\s*\)$")


def split_body_header(
    rows: List["TwoColRow"],
    *,
    body_anchor: int = 54,
    prelude_max_lines: int = 6,
    prelude_max_dy: float = 60.0,
) -> Tuple[List["TwoColRow"], List["TwoColRow"]]:
    """
    Split rows into (header, body) using (54) (or other anchor) as body start,
    but also pull a few left-content lines immediately ABOVE the anchor into the body.

    Key improvement: skips intervening right-only rows instead of stopping early.
    """
    rows = sorted(rows, key=lambda r: r.y)
    anchor = f"({body_anchor})"

    idx = None
    for i, r in enumerate(rows):
        if (r.left or "").strip() == anchor or (r.right or "").strip() == anchor:
            idx = i
            break

    if idx is None:
        return [], rows

    header = rows[:idx]
    body = rows[idx:]

    # Rescue "prelude" lines from header into body
    y_anchor = rows[idx].y
    pulled: List["TwoColRow"] = []
    pulled_count = 0

    # Walk upward; skip right-only rows; pull eligible left-content rows
    for r in reversed(header):
        if (y_anchor - r.y) > prelude_max_dy:
            break

        l = (r.left or "").strip()
        rr = (r.right or "").strip()

        # Stop if we hit another INID label (don’t cross label boundaries)
        if INID_RE.match(l) or INID_RE.match(rr):
            break

        # Skip right-only rows (e.g. “Related U.S. Application Data”)
        if not l and rr:
            continue

        # Pull meaningful left-content rows
        if l and len(l) >= 6:
            pulled.append(r)
            pulled_count += 1
            if pulled_count >= prelude_max_lines:
                break
        else:
            # empty row or tiny junk => stop
            break

    if pulled:
        pulled.reverse()

        # Remove the pulled rows from header (by identity)
        pulled_ids = {id(x) for x in pulled}
        header = [r for r in header if id(r) not in pulled_ids]

        # Prepend them to body
        body = pulled + body

    return header, body


_PUNCT_NO_SPACE_BEFORE = {",", ".", ";", ":", ")", "]", "}", "%"}
_PUNCT_NO_SPACE_AFTER = {"(", "[", "{"}


def _join_words_stably(words: list[tuple[float, float, float, float, str]]) -> str:
    if not words:
        return ""
    words = sorted(words, key=lambda w: w[0])
    out: list[str] = []
    prev = ""
    for x0, y0, x1, y1, t in words:
        t = t.strip()
        if not t:
            continue
        if not out:
            out.append(t)
        else:
            if (
                t in _PUNCT_NO_SPACE_BEFORE
                or prev in _PUNCT_NO_SPACE_AFTER
                or prev.endswith("-")
            ):
                out.append(t)
            else:
                out.append(" " + t)
        prev = t
    return "".join(out).strip()


def _split_line_by_largest_gap(
    line_words: list[tuple[float, float, float, float, str]],
    *,
    min_gap: float,
) -> tuple[
    list[tuple[float, float, float, float, str]],
    list[tuple[float, float, float, float, str]],
]:
    if len(line_words) < 2:
        return line_words, []
    ws = sorted(line_words, key=lambda w: w[0])
    best_gap = 0.0
    best_i = -1
    for i in range(len(ws) - 1):
        gap = ws[i + 1][0] - ws[i][2]
        if gap > best_gap:
            best_gap = gap
            best_i = i
    if best_gap < min_gap:
        return ws, []
    return ws[: best_i + 1], ws[best_i + 1 :]


def extract_two_column_rows(
    page: pymupdf.Page,
    *,
    header_margin: float = 20,
    footer_margin: float = 20,
    min_split_gap: float = 22.0,
    gutter: float = 10.0,  # dead-zone around midline
) -> list[TwoColRow]:
    """
    Returns y-sorted rows with robust left/right assignment.

    IMPORTANT: single-cluster lines are assigned left/right by their line bbox center x.
    """
    rect = page.rect
    x_mid = rect.width / 2.0

    y_min = header_margin
    y_max = rect.height - footer_margin

    raw = page.get_text("words") or []
    # words: x0,y0,x1,y1,text, block_no,line_no,word_no
    line_map: dict[tuple[int, int], list[tuple[float, float, float, float, str]]] = {}

    for w in raw:
        x0, y0, x1, y1, text, bno, lno, wno = w[:8]
        cy = (y0 + y1) * 0.5
        if cy < y_min or cy > y_max:
            continue
        t = str(text).strip()
        if not t:
            continue
        line_map.setdefault((int(bno), int(lno)), []).append(
            (float(x0), float(y0), float(x1), float(y1), t)
        )

    rows: list[TwoColRow] = []
    for (_bno, _lno), ws in line_map.items():
        minx = min(w[0] for w in ws)
        maxx = max(w[2] for w in ws)
        miny = min(w[1] for w in ws)
        maxy = max(w[3] for w in ws)
        cy = (miny + maxy) * 0.5
        cx = (minx + maxx) * 0.5

        left_words, right_words = _split_line_by_largest_gap(ws, min_gap=min_split_gap)

        # If we didn't split, decide which column this line belongs to by its center x
        if right_words == []:
            txt = _join_words_stably(left_words)
            if not txt:
                continue

            if cx > x_mid + gutter:
                rows.append(
                    TwoColRow(y=cy, left="", right=txt, left_x0=None, right_x0=minx)
                )
            else:
                rows.append(
                    TwoColRow(y=cy, left=txt, right="", left_x0=minx, right_x0=None)
                )
            continue

        left_txt = _join_words_stably(left_words)
        right_txt = _join_words_stably(right_words)

        left_x0 = min((w[0] for w in left_words), default=None)
        right_x0 = min((w[0] for w in right_words), default=None)

        if left_txt or right_txt:
            rows.append(
                TwoColRow(
                    y=cy,
                    left=left_txt,
                    right=right_txt,
                    left_x0=left_x0,
                    right_x0=right_x0,
                )
            )

    rows.sort(key=lambda r: r.y)
    return rows
