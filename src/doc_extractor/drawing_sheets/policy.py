from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DrawingSheetsStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class DrawingSheetsPolicy:
    require_at_least_one_region: bool = False
    expected_sheet_count: Optional[int] = None
    strict_expected_sheet_count: bool = False
    warnings_are_errors: bool = False
    max_regions_per_page: int = 50

    # NEW: heuristic enforcement
    validate_sheet_of_marker: bool = False
    strict_sheet_of_marker: bool = False
    min_sheet_of_hit_rate: float = 0.4  # warn if below this
