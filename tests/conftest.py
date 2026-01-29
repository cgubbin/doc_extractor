from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure `src/` is importable in pytest runs
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

EXPECTATIONS = Path(__file__).resolve().parent / "fixtures" / "expectations"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "pdfs"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def uspto_20110054659_pdf(fixtures_dir: Path) -> Path:
    return fixtures_dir / "US20110054659A1.pdf"


@pytest.fixture(scope="session")
def us_7629993B2_pdf(fixtures_dir: Path) -> Path:
    return fixtures_dir / "US7629993B2.pdf"


@pytest.fixture(scope="session")
def expectations_dir() -> Path:
    return EXPECTATIONS


def load_expectations(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
