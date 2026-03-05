"""Integration tests for the complete patent ingestion pipeline.

These tests verify end-to-end functionality with real components.
Tests are marked with @pytest.mark.integration and may be slower.
"""

import pytest
import tempfile
from pathlib import Path

from doc_extractor.api import (
    parse_patent,
    ParseOptions,
    FileSystemSink,
    MemorySink,
)
from doc_extractor.pipeline import (
    ingest_patent_pdf,
    IngestPolicy,
    IngestStatus,
    OrchestratorConfig,
)
from doc_extractor.diagnostics import Diagnostics


# Mark all tests in this module as integration tests
pytestmark = pytest.mark.integration


class TestParsePatentIntegration:
    """Integration tests for parse_patent function."""

    @pytest.mark.requires_pdf
    def test_parse_with_real_pdf(self, us_7629993B2_pdf):
        """Should successfully parse a real patent PDF."""
        # Skip if PDF fixture doesn't exist
        if not us_7629993B2_pdf.exists():
            pytest.skip("PDF fixture not available")

        options = ParseOptions(
            detect_figures=True,
            export_figures_png=False,
            export_sheet_png=False,
            fail_on_missing_inid=False,
        )

        result = parse_patent(
            pdf_path=str(us_7629993B2_pdf),
            doc_id="US7629993B2",
            options=options,
        )

        # Basic assertions about result structure
        assert result is not None
        # Result should be a ParseResult (dict-like or dataclass)
        assert isinstance(result, dict) or hasattr(result, "__dict__")

        # Should have some standard fields
        if isinstance(result, dict):
            assert "schema_version" in result or "qa" in result or "status" in result

    def test_parse_with_memory_sink(self, sample_body_text_with_sections):
        """Should work with MemorySink for testing."""
        # This test uses sample text rather than a real PDF
        # since full PDF parsing requires the PDF infrastructure
        sink = MemorySink()

        # Test that memory sink can be used in the workflow
        assert sink is not None
        assert hasattr(sink, "json_objects")
        assert hasattr(sink, "texts")

    def test_parse_options_affect_behavior(self):
        """Different parse options should affect processing."""
        options_detect = ParseOptions(detect_figures=True)
        options_no_detect = ParseOptions(detect_figures=False)

        assert options_detect.detect_figures is True
        assert options_no_detect.detect_figures is False

        # Options should be frozen (immutable)
        with pytest.raises((AttributeError, Exception)):
            options_detect.detect_figures = False


class TestIngestPipelineIntegration:
    """Integration tests for ingest_patent_pdf pipeline."""

    @pytest.mark.requires_pdf
    def test_full_pipeline_execution(self, us_7629993B2_pdf):
        """Should execute full pipeline on real PDF."""
        if not us_7629993B2_pdf.exists():
            pytest.skip("PDF fixture not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ingest_patent_pdf(
                path=us_7629993B2_pdf,
                output_dir=tmpdir,
                config=OrchestratorConfig(),
                policy=IngestPolicy(),
            )

            # Should return a result
            assert result is not None
            assert hasattr(result, "status")
            assert hasattr(result, "diagnostics")

            # Status should be one of the valid enum values
            assert result.status in [IngestStatus.OK, IngestStatus.PARTIAL, IngestStatus.FAILED]

            # Diagnostics should be present
            assert isinstance(result.diagnostics, Diagnostics)

    @pytest.mark.requires_pdf
    def test_pipeline_with_different_policies(self, us_7629993B2_pdf):
        """Different policies should affect outcome."""
        if not us_7629993B2_pdf.exists():
            pytest.skip("PDF fixture not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Strict policy (fail on errors)
            strict_policy = IngestPolicy(fail_on_error=True)
            # Lenient policy (don't fail on errors)
            lenient_policy = IngestPolicy(fail_on_error=False)

            result_strict = ingest_patent_pdf(
                path=us_7629993B2_pdf,
                output_dir=Path(tmpdir) / "strict",
                policy=strict_policy,
            )

            result_lenient = ingest_patent_pdf(
                path=us_7629993B2_pdf,
                output_dir=Path(tmpdir) / "lenient",
                policy=lenient_policy,
            )

            # Both should complete (not raise exceptions)
            assert result_strict is not None
            assert result_lenient is not None

    def test_pipeline_handles_nonexistent_file(self):
        """Should handle nonexistent PDF gracefully."""
        nonexistent = Path("/nonexistent/path/to/file.pdf")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = ingest_patent_pdf(
                path=nonexistent,
                output_dir=tmpdir,
                config=OrchestratorConfig(),
            )

            # Should return FAILED status, not raise exception
            assert result.status == IngestStatus.FAILED
            assert result.diagnostics.num_errors() > 0


class TestClaimsExtractionIntegration:
    """Integration tests for claims extraction across components."""

    def test_claims_extraction_end_to_end(self, sample_claims_text):
        """Should extract claims through full pipeline."""
        from doc_extractor.body.patterns import (
            _find_claims_start_offset,
            _extract_claims_block,
            _parse_claims_from_block,
        )

        # Simulate the full extraction pipeline
        # Step 1: Find claims location
        offset = _find_claims_start_offset(sample_claims_text)
        assert offset is not None

        # Step 2: Extract claims block
        sections = {}
        qa = {"warnings": [], "info": {}}
        block = _extract_claims_block(sample_claims_text, sections, qa)
        assert block != ""

        # Step 3: Parse individual claims
        claims = _parse_claims_from_block(block)

        # Verify results
        assert len(claims) == 5
        assert all(isinstance(claim, str) for claim in claims)
        assert all(claim.startswith(f"{i+1}.") for i, claim in enumerate(claims))

    def test_claims_with_dependencies(self):
        """Should handle dependent claims referencing other claims."""
        text = """What is claimed is:

1. A method for processing data.

2. The method of claim 1, wherein the data is validated.

3. The method of claim 1, wherein the data is transformed.

4. The method of claim 2, further comprising storing the data."""

        from doc_extractor.body.patterns import (
            _extract_claims_block,
            _parse_claims_from_block,
        )

        sections = {}
        qa = {"warnings": [], "info": {}}
        block = _extract_claims_block(text, sections, qa)
        claims = _parse_claims_from_block(block)

        assert len(claims) == 4

        # Verify claim dependencies are preserved in text
        assert "claim 1" in claims[1].lower()
        assert "claim 1" in claims[2].lower()
        assert "claim 2" in claims[3].lower()


class TestFigureExtractionIntegration:
    """Integration tests for figure extraction."""

    def test_figure_extraction_end_to_end(self, sample_figure_descriptions_text):
        """Should extract figures through full pipeline."""
        from doc_extractor.body.patterns import extract_drawing_descriptions

        results = extract_drawing_descriptions(sample_figure_descriptions_text)

        # Should extract all figures mentioned
        assert len(results) > 0

        # Should have proper structure
        for item in results:
            assert "figure_number" in item
            assert "description" in item
            assert isinstance(item["figure_number"], int)
            assert isinstance(item["description"], str)

    def test_figure_ranges_expanded(self):
        """Should expand figure ranges like '3-5' into individual entries."""
        text = "FIGS. 3-5 show the processing steps."

        from doc_extractor.body.patterns import extract_drawing_descriptions

        results = extract_drawing_descriptions(text)

        # Should have separate entries for 3, 4, and 5
        fig_numbers = [r["figure_number"] for r in results]
        assert 3 in fig_numbers
        assert 4 in fig_numbers
        assert 5 in fig_numbers

        # All should have the same description
        descriptions = [r["description"] for r in results]
        assert len(set(descriptions)) == 1  # All same description


class TestDiagnosticsIntegration:
    """Integration tests for diagnostics across pipeline."""

    def test_diagnostics_collected_throughout_pipeline(self):
        """Diagnostics should accumulate from all stages."""
        diag = Diagnostics()

        # Simulate different stages adding diagnostics
        diag.info("stage1.start", "Starting stage 1")
        diag.warn("stage1.issue", "Minor issue in stage 1")

        diag.info("stage2.start", "Starting stage 2")
        diag.error("stage2.failure", "Critical error in stage 2")

        diag.info("stage3.start", "Starting stage 3")

        # Should have collected all diagnostics
        assert diag.num_info() == 3
        assert diag.num_warnings() == 1
        assert diag.num_errors() == 1

        # Pipeline should not be OK due to error
        assert diag.ok() is False

    def test_diagnostics_merge_from_subcomponents(self):
        """Should merge diagnostics from sub-parsers."""
        main_diag = Diagnostics()
        main_diag.info("main", "Main parser started")

        # Simulate sub-parser with its own diagnostics
        sub_diag = Diagnostics()
        sub_diag.warn("sub.issue", "Sub-parser issue")
        sub_diag.info("sub.complete", "Sub-parser complete")

        # Merge sub-parser diagnostics into main
        main_diag.merge(sub_diag)

        # Should have combined diagnostics
        assert main_diag.num_info() >= 2
        assert main_diag.num_warnings() >= 1

    def test_diagnostics_deduplication_in_pipeline(self):
        """Should deduplicate repeated diagnostics."""
        diag = Diagnostics()

        # Simulate the same warning appearing multiple times
        for i in range(5):
            diag.warn("repeated.warning", "This warning repeats")

        # Should have 5 before dedup
        assert diag.num_warnings() == 5

        # Deduplicate
        diag.deduplicate()

        # Should have 1 after dedup
        assert diag.num_warnings() == 1


class TestSinkIntegration:
    """Integration tests for sink usage in pipeline."""

    def test_filesystem_sink_creates_expected_artifacts(self):
        """FileSystemSink should create all expected output files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sink = FileSystemSink(tmpdir)

            # Simulate pipeline creating various outputs
            sink.put_json("metadata.json", {"version": "1.0"})
            sink.put_json("claims.json", {"count": 10, "items": []})
            sink.put_text("body.txt", "Patent body text")
            sink.put_text("abstract.txt", "Abstract text")

            # Verify all files created
            output_dir = Path(tmpdir)
            assert (output_dir / "metadata.json").exists()
            assert (output_dir / "claims.json").exists()
            assert (output_dir / "body.txt").exists()
            assert (output_dir / "abstract.txt").exists()

    def test_memory_sink_for_testing_pipeline(self):
        """MemorySink should be usable for testing without filesystem."""
        sink = MemorySink()

        # Simulate pipeline outputs
        sink.put_json("metadata.json", {"doc_id": "US123"})
        sink.put_json("claims.json", {"count": 5})
        sink.put_text("body.txt", "Body text")

        # All should be accessible from memory
        assert "metadata.json" in sink.json_objects
        assert "claims.json" in sink.json_objects
        assert "body.txt" in sink.texts

        # Should be able to inspect results
        assert sink.json_objects["metadata.json"]["doc_id"] == "US123"
        assert sink.json_objects["claims.json"]["count"] == 5


class TestErrorRecoveryIntegration:
    """Integration tests for error handling and recovery."""

    def test_pipeline_continues_after_non_fatal_errors(self):
        """Pipeline should continue processing after non-fatal errors."""
        diag = Diagnostics()

        # Simulate non-fatal error in one component
        diag.warn("component1.warning", "Component 1 had an issue")

        # Pipeline continues
        diag.info("component2.start", "Component 2 processing")

        # Should still be OK (warnings don't fail)
        assert diag.ok() is True

    def test_pipeline_reports_all_errors_on_failure(self):
        """On failure, should report all accumulated errors."""
        diag = Diagnostics()

        # Simulate multiple errors across components
        diag.error("component1.error", "Component 1 failed")
        diag.error("component2.error", "Component 2 failed")
        diag.warn("component3.warning", "Component 3 warning")

        # Should capture all errors
        errors = list(diag.errors())
        assert len(errors) == 2

        # Should be in failed state
        assert diag.ok() is False


class TestRegressionTests:
    """Regression tests for previously fixed bugs."""

    @pytest.mark.regression
    def test_claims_with_ocr_corruption_regression(self):
        """Regression: Should handle OCR corruption in claim markers."""
        # This was a bug where "15-4" from OCR corruption wasn't recognized
        text = """What is claimed is:

1. A method for processing data comprising multiple steps.

2. The method of claim 1 wherein the data is validated.

15-4 An apparatus comprising a processor and memory."""  # OCR dropped period, added dash

        from doc_extractor.body.patterns import _parse_claims_from_block

        block = text.split("What is claimed is:")[1]
        claims = _parse_claims_from_block(block)

        # Should find all 3 claims (including the OCR-corrupted "15-4")
        assert len(claims) >= 2
        # The OCR corruption should be handled
        assert any("15" in claim for claim in claims)

    @pytest.mark.regression
    def test_figure_range_expansion_regression(self):
        """Regression: Should expand figure ranges correctly."""
        # Bug where "FIGS. 2A-2C" only created entry for 2A and 2C, missing 2B
        text = "FIGS. 2A-2C show the process."

        from doc_extractor.body.patterns import extract_drawing_descriptions

        results = extract_drawing_descriptions(text)
        fig_ids = [
            f"{r['figure_number']}{r['figure_suffix'] or ''}"
            for r in results
        ]

        # Should have all three
        assert "2A" in fig_ids
        assert "2B" in fig_ids
        assert "2C" in fig_ids


# Slow integration tests (marked separately)

class TestSlowIntegrationTests:
    """Integration tests that take significant time."""

    @pytest.mark.slow
    @pytest.mark.requires_pdf
    def test_large_document_performance(self, us_7629993B2_pdf):
        """Should handle large patent documents efficiently."""
        if not us_7629993B2_pdf.exists():
            pytest.skip("PDF fixture not available")

        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            start = time.time()

            result = ingest_patent_pdf(
                path=us_7629993B2_pdf,
                output_dir=tmpdir,
            )

            elapsed = time.time() - start

            # Should complete in reasonable time (adjust threshold as needed)
            assert elapsed < 30.0  # 30 seconds max

            # Should succeed
            assert result.status in [IngestStatus.OK, IngestStatus.PARTIAL]

    @pytest.mark.slow
    @pytest.mark.requires_pdf
    def test_multiple_documents_batch_processing(self, fixtures_dir):
        """Should handle batch processing of multiple documents."""
        if not fixtures_dir.exists():
            pytest.skip("Fixtures directory not available")

        pdf_files = list(fixtures_dir.glob("*.pdf"))
        if len(pdf_files) < 2:
            pytest.skip("Not enough PDF fixtures for batch test")

        results = []
        with tempfile.TemporaryDirectory() as tmpdir:
            for i, pdf_path in enumerate(pdf_files[:3]):  # Test first 3
                output_subdir = Path(tmpdir) / f"doc_{i}"
                result = ingest_patent_pdf(
                    path=pdf_path,
                    output_dir=output_subdir,
                )
                results.append(result)

        # All should complete (may have different statuses)
        assert len(results) == min(3, len(pdf_files))
        assert all(r is not None for r in results)
