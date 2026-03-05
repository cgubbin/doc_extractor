# Test Suite for Patent Ingestion System

This directory contains comprehensive unit and integration tests for the patent ingestion system.

## Structure

```
tests/
├── conftest.py                  # Pytest fixtures and configuration
├── test_body_patterns.py        # Tests for claims/figure extraction (60+ tests)
├── test_api.py                  # Tests for file sinks and API (40+ tests)
├── test_diagnostics.py          # Tests for diagnostics system (35+ tests)
├── test_integration_pipeline.py # End-to-end pipeline tests
├── fixtures/                    # Test data
│   ├── pdfs/                    # Sample PDF files
│   └── expectations/            # Expected outputs
└── README.md                    # This file
```

## Running Tests

### Run all tests
```bash
pytest
```

### Run specific test file
```bash
pytest tests/test_body_patterns.py
```

### Run specific test class
```bash
pytest tests/test_body_patterns.py::TestClaimsAnchorRegex
```

### Run specific test
```bash
pytest tests/test_body_patterns.py::TestClaimsAnchorRegex::test_matches_what_is_claimed_is
```

### Run tests with markers
```bash
# Only unit tests
pytest -m unit

# Only integration tests
pytest -m integration

# Exclude slow tests
pytest -m "not slow"

# Only tests requiring PDFs
pytest -m requires_pdf
```

### Run with coverage report
```bash
# HTML report (opens in browser)
pytest --cov=doc_extractor --cov-report=html
open htmlcov/index.html

# Terminal report
pytest --cov=doc_extractor --cov-report=term-missing
```

### Run in parallel (if pytest-xdist installed)
```bash
pytest -n auto
```

### Run with verbose output
```bash
pytest -v

# Extra verbose (show test docstrings)
pytest -vv
```

## Test Organization

### Unit Tests
Test individual functions and classes in isolation:
- `test_body_patterns.py`: Regex patterns, claims extraction, figure parsing
- `test_api.py`: File sinks, configuration
- `test_diagnostics.py`: Diagnostic collection and reporting

### Integration Tests
Test complete workflows with real components:
- `test_integration_pipeline.py`: End-to-end PDF processing

### Test Markers

Tests are marked with pytest markers for organization:

- `@pytest.mark.unit`: Unit tests (fast, isolated)
- `@pytest.mark.integration`: Integration tests (slower, require components)
- `@pytest.mark.slow`: Tests that take >1 second
- `@pytest.mark.requires_pdf`: Tests that need PDF fixtures
- `@pytest.mark.regression`: Tests for previously fixed bugs

## Writing New Tests

### Test File Naming
- Unit test files: `test_<module_name>.py`
- Integration tests: `test_integration_<feature>.py`

### Test Class Naming
- `class TestFunctionName`: Group related tests
- `class TestModuleFeature`: Group feature tests

### Test Function Naming
- `test_<behavior>`: Describe what is being tested
- Use underscores for readability
- Be descriptive: `test_matches_what_is_claimed_is` not `test_match`

### Example Test Structure

```python
class TestClaimsExtraction:
    \"\"\"Test claims extraction functionality.\"\"\"

    @pytest.fixture
    def sample_text(self):
        \"\"\"Sample text for testing.\"\"\"
        return "What is claimed is:\n\n1. A method..."

    def test_finds_claims_anchor(self, sample_text):
        \"\"\"Should find claims anchor phrase.\"\"\"
        offset = _find_claims_start_offset(sample_text)
        assert offset is not None

    @pytest.mark.slow
    def test_large_document_performance(self):
        \"\"\"Should handle large documents efficiently.\"\"\"
        # Test implementation
        pass
```

### Using Fixtures

Fixtures are defined in `conftest.py` and automatically available in all tests:

```python
def test_with_fixtures(sample_claims_text, sample_figure_descriptions_text):
    # Use fixtures directly as parameters
    assert "What is claimed is" in sample_claims_text
```

## Code Coverage

Target coverage: **60%** minimum for v0.1 release

Current coverage can be viewed by running:
```bash
pytest --cov=doc_extractor --cov-report=term
```

### Coverage Goals by Module
- `body/patterns.py`: 80%+ (critical extraction logic)
- `body/parse.py`: 70%+ (parsing logic)
- `api.py`: 90%+ (simple I/O)
- `pipeline.py`: 60%+ (integration)
- `diagnostics.py`: 95%+ (utility)

## Continuous Integration

Tests should be run in CI on:
- Every pull request
- Every push to main branch
- Nightly builds

### CI Commands
```bash
# Full test suite with coverage
pytest --cov=doc_extractor --cov-report=xml --cov-fail-under=60

# Quick smoke test
pytest -m "not slow" --maxfail=1
```

## Debugging Failed Tests

### Show print statements
```bash
pytest -s tests/test_body_patterns.py
```

### Drop into debugger on failure
```bash
pytest --pdb
```

### Show full diffs
```bash
pytest -vv
```

### Run only failed tests from last run
```bash
pytest --lf
```

### Run failed tests first, then others
```bash
pytest --ff
```

## Performance Testing

### Measure test duration
```bash
pytest --durations=10
```

### Profile test execution
```bash
pytest --profile
```

## Common Issues

### Import Errors
Make sure `src/` is in your Python path. This is configured in `conftest.py`.

### PDF Fixture Not Found
Check that fixture PDFs exist in `tests/fixtures/pdfs/`. Some tests are marked with `@pytest.mark.requires_pdf`.

### Coverage Too Low
Run `pytest --cov --cov-report=html` and open `htmlcov/index.html` to see which lines need coverage.

## Adding New Test Fixtures

1. Add sample data to `tests/fixtures/`
2. Create fixture in `conftest.py`:
```python
@pytest.fixture
def my_fixture():
    return "test data"
```
3. Use in tests as function parameter

## Dependencies

Required for testing:
- `pytest >= 7.0`
- `pytest-cov` (for coverage)

Optional:
- `pytest-xdist` (parallel execution)
- `pytest-timeout` (timeout protection)
- `pytest-mock` (mocking utilities)

Install with:
```bash
pip install pytest pytest-cov pytest-xdist
```

## Contributing

When adding new features:
1. Write tests first (TDD)
2. Ensure all tests pass
3. Maintain >60% coverage
4. Add appropriate markers
5. Update this README if needed

## Questions?

For questions about testing, see:
- [pytest documentation](https://docs.pytest.org/)
- Project maintainers
- Existing test examples in this directory
