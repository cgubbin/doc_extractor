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
    # structural
    require_at_least_one_region: bool = True

    # expected count checks (optional: if you know expected sheets or expected drawings)
    expected_sheet_count: Optional[int] = None
    strict_expected_sheet_count: bool = False

    # if you treat warnings as errors for QA runs
    warnings_are_errors: bool = False

    # safety cap / guardrails
    max_regions_per_page: int = 50
