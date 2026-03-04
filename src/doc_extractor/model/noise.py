from __future__ import annotations

from typing import List, Optional, Tuple
from .model import Line


def detect_noise_cutoff_y(
    lines: List[Line],
    *,
    min_gap: float = 70.0,
    min_y: float = 200.0,
) -> Optional[float]:
    """
    Finds a cutoff using the largest vertical gap after min_y.
    Useful for front-matter pages where a stamp/garbage zone appears far below the abstract.
    """
    if len(lines) < 8:
        return None

    ys = [ln.y for ln in sorted(lines, key=lambda x: x.y)]
    best_gap = 0.0
    best_mid = None

    for a, b in zip(ys[:-1], ys[1:]):
        if a < min_y:
            continue
        gap = b - a
        if gap >= min_gap and gap > best_gap:
            best_gap = gap
            best_mid = 0.5 * (a + b)

    return best_mid


def apply_cutoff(
    lines: List[Line], cutoff_y: Optional[float]
) -> Tuple[List[Line], List[Line]]:
    if cutoff_y is None:
        return lines, []
    kept = [ln for ln in lines if ln.y < cutoff_y]
    cut = [ln for ln in lines if ln.y >= cutoff_y]
    return kept, cut
