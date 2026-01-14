import re
from dataclasses import dataclass
from typing import List, Tuple


@dataclass
class _Frag:
    x: float
    y: float
    text: str


def _compute_split_from_width(page) -> float:
    # pypdf mediabox gives the page width; midpoint is a robust split for USPTO two-column pages
    try:
        w = float(page.mediabox.width)
        return w / 2.0
    except Exception:
        return 0.0


def _compute_split_from_quantiles(xs: List[float]) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    n = len(xs)
    q25 = xs[int(0.25 * (n - 1))]
    q75 = xs[int(0.75 * (n - 1))]
    # If x positions show two clusters, midpoint between quartiles is a good split
    if (q75 - q25) > 50:
        return (q25 + q75) / 2.0
    # Otherwise, fallback: largest gap between unique x’s
    uniq = sorted(set(xs))
    if len(uniq) >= 2:
        best_gap = -1.0
        best_mid = uniq[0]
        for a, b in zip(uniq, uniq[1:]):
            gap = b - a
            mid = (a + b) / 2.0
            if gap > best_gap:
                best_gap = gap
                best_mid = mid
        return best_mid
    return xs[n // 2]


def extract_page_text_two_column(reader, page_index: int, *, y_tol: float = 2.5) -> str:
    """
    Reconstruct text order for USPTO-style two-column pages:
      - group fragments into lines by y (within y_tol)
      - split each line into left/right by a robust x_split
      - emit left column top-to-bottom, then right column top-to-bottom
    """
    page = reader.pages[page_index]
    frags: List[_Frag] = []

    def visitor_text(text, cm, tm, fontDict, fontSize):
        try:
            x = float(tm[4])
            y = float(tm[5])
        except Exception:
            return
        t = (text or "").strip()
        if t:
            frags.append(_Frag(x=x, y=y, text=t))

    page.extract_text(visitor_text=visitor_text)

    if not frags:
        return ""

    # Sort by visual order (top-to-bottom, left-to-right)
    frags.sort(key=lambda f: (-f.y, f.x))

    # Cluster into lines by y
    lines: List[Tuple[float, List[_Frag]]] = []
    for f in frags:
        if not lines:
            lines.append((f.y, [f]))
            continue
        y0, lst = lines[-1]
        if abs(f.y - y0) <= y_tol:
            lst.append(f)
        else:
            lines.append((f.y, [f]))

    # Sort fragments in each line by x
    lines = [(y0, sorted(lst, key=lambda f: f.x)) for (y0, lst) in lines]

    xs = [f.x for f in frags]

    # Primary split: page midpoint. Fallback: quantile-based split.
    x_split = _compute_split_from_width(page)
    if x_split <= 0:
        x_split = _compute_split_from_quantiles(xs)

    left_lines: List[str] = []
    right_lines: List[str] = []

    for _, lst in lines:
        left = [f.text for f in lst if f.x < x_split]
        right = [f.text for f in lst if f.x >= x_split]
        if left:
            left_lines.append(" ".join(left))
        if right:
            right_lines.append(" ".join(right))

    text_out = "\n".join(left_lines).strip() + "\n\n" + "\n".join(right_lines).strip()
    text_out = re.sub(r"[ \t]+", " ", text_out)
    text_out = re.sub(r"\n{3,}", "\n\n", text_out).strip()
    return text_out
