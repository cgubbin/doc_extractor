from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from patent_ingest.model.segment_inid import inid_label_count


@dataclass(frozen=True)
class PageType:
    kind: Literal["inid", "body", "drawing", "unknown"]
    inid_labels: int
    para_markers: int


SHEET_RE = re.compile(r"\bSheet\s+\d+\s+of\s+\d+\b", re.IGNORECASE)
FIG_RE = re.compile(r"^\s*Fig\.\s*\d+\b", re.IGNORECASE)
PARA_RE = re.compile(r"^\s*\d{4}\s*[.\)]\s*")


def _para_count(layout, region="body") -> int:
    c = 0
    for col in ("L", "R"):
        for ln in layout.stream(region, col).lines:
            if PARA_RE.match(ln.text):
                c += 1
    return c


def _header_text(layout) -> str:
    parts = []
    for col in ("L", "R"):
        parts.extend(ln.text for ln in layout.header[col].lines if ln.text)
    return " ".join(parts)


def _body_text(layout) -> str:
    parts = []
    for col in ("L", "R"):
        parts.extend(ln.text for ln in layout.body[col].lines if ln.text)
    return " ".join(parts)


def classify_page(layout, *, region="body"):
    inids = inid_label_count(layout.stream(region, "L")) + inid_label_count(
        layout.stream(region, "R")
    )
    paras = _para_count(layout, region=region)

    header = _header_text(layout)
    body = _body_text(layout)

    # 1) Drawing sheets: header "Sheet X of Y" is decisive
    if SHEET_RE.search(header):
        return PageType("drawing", inids, paras)

    # 2) Also treat as drawing if it has Fig labels but no paragraph markers and no INID run
    if FIG_RE.search(body) and paras == 0 and inids < 3:
        return PageType("drawing", inids, paras)

    # 3) INID / body as before
    if inids >= 3 and paras < 2:
        return PageType("inid", inids, paras)
    if paras >= 2 and inids < 3:
        return PageType("body", inids, paras)
    if inids >= 3 and paras >= 2:
        return PageType("body", inids, paras)

    return PageType("unknown", inids, paras)
