from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Literal
import re
import statistics

from patent_ingest.model.model import Block, ColumnStream, Region
from patent_ingest.common.section_rules import is_known_section_heading


@dataclass(frozen=True)
class ParagraphBlock:
    page: int
    col: Literal["L", "R"]
    y0: float
    y1: float
    kind: Literal["section_heading", "paragraph", "enumerator", "para_marker"]
    text: str


# ---------------------------
# Line role classification
# ---------------------------

# "Caps-ish" heading line (used for subheadings only)
CAPS_HEADING_RE = re.compile(r"^[A-Z0-9][A-Z0-9\s\-:,]{3,}$")

# Enumerators/labels that are NOT section boundaries
ENUM_ONLY_RE = re.compile(r"^\s*(?:\d+|[IVXLC]+|[A-Z])(?:[.)]|:)?\s*$")
PAREN_ENUM_RE = re.compile(r"^\s*\(\s*\d+\s*\)\s*$")

# Sentence end heuristic
_SENT_END_RE = re.compile(r"[.!?][\"')\]]?\s*$")


PARA_MARK_RE = re.compile(r"^\s*\d{4}\s*(?:[.:)\]]\s*)?.*$")  # 0017, 0017., 0017: ...
PARA_NUM_ONLY_RE = re.compile(
    r"^\s*\d{4}\s*(?:[.:)\]]\s*)?$"
)  # line is just the marker


def classify_line_role(
    text: str,
) -> Literal["section_heading", "subheading", "enumerator", "para_marker", "paragraph"]:
    t = (text or "").strip()
    if not t:
        return "paragraph"

    # True section headings: delegated to common/section_rules — single source of truth.
    if is_known_section_heading(t):
        return "section_heading"

    # If we see a 4-digit marker at the start, treat as paragraph marker
    # (We don't require it to exist; we just handle it correctly when present.)
    if PARA_MARK_RE.match(t):
        return "para_marker"

    # Enumerators / labels (NOT section boundaries)
    if ENUM_ONLY_RE.match(t) or PAREN_ENUM_RE.match(t):
        return "enumerator"

    # Subheading candidates (caps-ish short line)
    if len(t) <= 90 and CAPS_HEADING_RE.match(t) and not t.endswith("."):
        return "subheading"

    return "paragraph"


# ---------------------------
# Helpers for geometry signals
# ---------------------------


def _robust_mode(values: List[float], bin_size: float = 2.0) -> Optional[float]:
    """Histogram mode with binning; helps estimate left margin from noisy x0 values."""
    if not values:
        return None
    bins = {}
    for v in values:
        b = round(v / bin_size) * bin_size
        bins[b] = bins.get(b, 0) + 1
    return max(bins.items(), key=lambda kv: kv[1])[0]


def segment_paragraph_blocks(
    stream: ColumnStream,
    *,
    region: Region,
    # Emit heading-like blocks separately
    emit_heading_blocks: bool = True,
    # Whether subheadings should behave like section boundaries (usually True for section slicing)
    subheadings_are_boundaries: bool = True,
    # y-gap sensitivity
    gap_mult: float = 2.4,
    min_gap: float = 16.0,
    # indent sensitivity (requires x0)
    indent_thresh: float = 10.0,
    # "short line" heuristic (requires x0/x1 or falls back to text length)
    short_frac: float = 0.62,
    min_chars_long_line: int = 35,
    # Avoid producing tiny blocks
    min_lines_per_block: int = 1,
) -> List[Block]:
    """
    Paragraph segmentation for patent body text WITHOUT relying on paragraph numbers.

    Produces blocks of kinds:
      - "section_heading"  (true section boundary; whitelist)
      - "subheading"       (caps-ish line; optional boundary)
      - "paragraph"        (normal prose)
      - "enumerator" is NOT emitted as its own block by default; it is kept with the paragraph
        because it is usually an inline label and not a useful section boundary.

    Boundary signals:
      - heading lines (hard boundary if emitted; optional for subheading)
      - vertical y-gap outliers
      - indentation / margin reset (if x0 present)
      - short-line + punctuation + margin reset (raggedness)
    """
    lines = [ln for ln in stream.lines if (ln.text or "").strip()]
    if not lines:
        return []

    # --- Estimate left margin and typical line width for the column ---
    candidate_x0: List[float] = []
    widths: List[float] = []

    for ln in lines:
        role = classify_line_role(ln.text)
        if role in ("section_heading", "subheading"):
            continue
        if ln.x0 is None or ln.x1 is None:
            continue
        t = ln.text.strip()
        if len(t) >= min_chars_long_line:
            candidate_x0.append(float(ln.x0))
            widths.append(float(ln.x1 - ln.x0))

    left_margin = _robust_mode(candidate_x0)  # may be None
    typical_width = statistics.median(widths) if widths else None

    # --- Typical y-gap ---
    ys = [ln.y for ln in lines]
    gaps = [ys[i + 1] - ys[i] for i in range(len(ys) - 1) if (ys[i + 1] - ys[i]) > 0]
    med_gap = statistics.median(gaps) if gaps else 10.0
    gap_thresh = max(min_gap, gap_mult * med_gap)

    def is_short_line(ln) -> bool:
        if typical_width is None or ln.x0 is None or ln.x1 is None:
            return len(ln.text.strip()) < 45
        return (ln.x1 - ln.x0) < (short_frac * typical_width)

    def near_left_margin(x0: Optional[float]) -> bool:
        if left_margin is None or x0 is None:
            return False
        return abs(x0 - left_margin) <= 3.5

    def indented(x0: Optional[float]) -> bool:
        if left_margin is None or x0 is None:
            return False
        return (x0 - left_margin) >= indent_thresh

    blocks: List[Block] = []
    buf: List[int] = []

    def flush_paragraph() -> None:
        nonlocal buf
        if not buf:
            return
        chunk = [lines[i] for i in buf]
        if len(chunk) < min_lines_per_block:
            buf = []
            return
        text = "\n".join(ln.text.strip() for ln in chunk if ln.text).strip()
        if not text:
            buf = []
            return
        blocks.append(
            Block(
                col=stream.col,
                region=region,
                y0=chunk[0].y0,
                y1=chunk[-1].y1,
                kind="paragraph",
                tag=None,
                text=text,
            )
        )
        buf = []

    # --- Main scan ---
    for i, ln in enumerate(lines):
        t = ln.text.strip()
        role = classify_line_role(t)

        # Hard boundary: section headings always split paragraphs
        if emit_heading_blocks and role == "section_heading":
            flush_paragraph()
            blocks.append(
                Block(stream.col, region, ln.y0, ln.y1, "section_heading", None, t)
            )
            continue

        # Subheadings: optionally behave as boundaries (usually yes for section slicing)
        if emit_heading_blocks and role == "subheading" and subheadings_are_boundaries:
            flush_paragraph()
            blocks.append(
                Block(stream.col, region, ln.y0, ln.y1, "subheading", None, t)
            )
            continue

        # Enumerators: Multi-digit numeric enumerators (claim numbers) start new paragraphs.
        # Single-letter/roman numerals are kept inline.
        if role == "enumerator":
            # Check if this is a multi-digit claim number (1-3 digits + period)
            # These should start new paragraphs for proper claim separation
            if re.match(r'^\s*\d{1,3}\s*\.\s*$', t):
                flush_paragraph()
                buf.append(i)
            else:
                # Single letters/roman numerals: keep inline
                buf.append(i)
            continue
        if role == "para_marker":
            # Start a new paragraph block at each marker
            flush_paragraph()
            buf.append(i)
            continue

        # Decide whether to start a new paragraph using geometry + punctuation
        new_para = False
        if buf:
            prev = lines[buf[-1]]

            # 1) big vertical gap
            if (ln.y - prev.y) >= gap_thresh:
                new_para = True

            # 2) first-line indent after sentence end / short line
            if (
                not new_para
                and indented(ln.x0)
                and (near_left_margin(prev.x0) or prev.x0 is None)
            ):
                if _SENT_END_RE.search(prev.text.strip()) or is_short_line(prev):
                    new_para = True

            # 3) hanging indent reset: indented previous, current returns to margin
            if not new_para and near_left_margin(ln.x0) and indented(prev.x0):
                new_para = True

            # 4) raggedness: short previous line + margin reset + punctuation
            if not new_para and is_short_line(prev) and near_left_margin(ln.x0):
                if _SENT_END_RE.search(prev.text.strip()):
                    new_para = True

        if new_para:
            flush_paragraph()

        buf.append(i)

    flush_paragraph()
    blocks.sort(key=lambda b: b.y0)
    return blocks
