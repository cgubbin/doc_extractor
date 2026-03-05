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


# Additional test fixtures for unit testing

@pytest.fixture
def sample_claims_text() -> str:
    """Sample claims text with standard formatting."""
    return """What is claimed is:

1. A method for processing data, the method comprising:
   receiving input data from a source;
   transforming the input data using a transformation algorithm; and
   outputting the transformed data to a destination.

2. The method of claim 1, wherein the transformation algorithm comprises
a machine learning model.

3. The method of claim 1, further comprising validating the input data
before transforming.

4. An apparatus comprising:
   a processor configured to execute instructions; and
   a memory storing the instructions that, when executed by the processor,
   cause the apparatus to perform the method of claim 1.

5. The apparatus of claim 4, wherein the processor is a multi-core processor."""


@pytest.fixture
def sample_claims_text_with_ocr_errors() -> str:
    """Sample claims text with OCR corruption (dropped periods, wrong separators)."""
    return """What is claimed is:

1. A method for processing data, the method comprising:
   receiving input data from a source;

2- The method of claim 1, wherein the transformation algorithm comprises
a machine learning model.

3) The method of claim 1, further comprising validating the input data

15-4 An apparatus comprising:
   a processor configured to execute instructions;"""


@pytest.fixture
def sample_figure_descriptions_text() -> str:
    """Sample figure descriptions section with various formats."""
    return """BRIEF DESCRIPTION OF THE DRAWINGS

FIG. 1 is a block diagram illustrating an exemplary system architecture.

FIG. 2A is a flowchart showing a first processing step.

FIG. 2B is a flowchart showing a second processing step.

FIG. 2C is a flowchart showing a third processing step.

FIGS. 3-5 are diagrams illustrating various data structures used in the system.

FIGS. 6 and 7 are graphs showing performance characteristics."""


@pytest.fixture
def sample_body_text_with_sections() -> str:
    """Complete patent body text with all standard sections."""
    return """BACKGROUND OF THE INVENTION

This invention relates to data processing systems and methods.
Prior art systems suffer from various limitations.

SUMMARY OF THE INVENTION

The present invention provides a novel approach to data processing
that improves efficiency and accuracy. The invention comprises
a method and apparatus for enhanced data transformation.

BRIEF DESCRIPTION OF THE DRAWINGS

FIG. 1 illustrates the system architecture.
FIG. 2 shows the processing flow.

DETAILED DESCRIPTION

The following detailed description explains the invention in detail.
Various embodiments are described with reference to the drawings.

What is claimed is:

1. A method for processing data, the method comprising:
   receiving input data from a source;
   transforming the input data using a transformation algorithm; and
   outputting the transformed data to a destination."""
