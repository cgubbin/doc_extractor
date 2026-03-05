"""Unit tests for doc_extractor.diagnostics module.

Tests cover:
- Issue dataclass
- Severity enum
- Diagnostics collection and querying
- Diagnostic merging and deduplication
"""

import pytest
from doc_extractor.diagnostics import (
    Issue,
    Severity,
    Diagnostics,
)


class TestSeverity:
    """Test Severity enum."""

    def test_has_all_levels(self):
        """Should have ERROR, WARNING, and INFO levels."""
        assert hasattr(Severity, "ERROR")
        assert hasattr(Severity, "WARNING")
        assert hasattr(Severity, "INFO")

    def test_string_values(self):
        """Should have appropriate string values."""
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"

    def test_equality(self):
        """Should support equality comparison."""
        assert Severity.ERROR == Severity.ERROR
        assert Severity.WARNING != Severity.ERROR


class TestIssue:
    """Test Issue dataclass."""

    def test_creation_minimal(self):
        """Should create issue with minimal required fields."""
        issue = Issue(
            severity=Severity.ERROR,
            code="test.error",
            message="Test error message",
        )

        assert issue.severity == Severity.ERROR
        assert issue.code == "test.error"
        assert issue.message == "Test error message"
        assert issue.inid is None
        assert issue.meta == {}

    def test_creation_with_all_fields(self):
        """Should create issue with all fields."""
        issue = Issue(
            severity=Severity.WARNING,
            code="test.warning",
            message="Test warning",
            inid="54",
            meta={"detail": "extra info", "count": 5},
        )

        assert issue.severity == Severity.WARNING
        assert issue.code == "test.warning"
        assert issue.message == "Test warning"
        assert issue.inid == "54"
        assert issue.meta["detail"] == "extra info"
        assert issue.meta["count"] == 5

    def test_is_frozen(self):
        """Should be immutable (frozen dataclass)."""
        issue = Issue(
            severity=Severity.INFO,
            code="test",
            message="message",
        )

        # Should not be able to modify
        with pytest.raises((AttributeError, Exception)):
            issue.code = "modified"

    def test_different_severities(self):
        """Should handle different severity levels."""
        error_issue = Issue(Severity.ERROR, "e", "Error")
        warning_issue = Issue(Severity.WARNING, "w", "Warning")
        info_issue = Issue(Severity.INFO, "i", "Info")

        assert error_issue.severity == Severity.ERROR
        assert warning_issue.severity == Severity.WARNING
        assert info_issue.severity == Severity.INFO


class TestDiagnostics:
    """Test Diagnostics collection."""

    def test_initialization_empty(self):
        """Should initialize with empty issues list."""
        diag = Diagnostics()
        assert len(diag.issues) == 0

    def test_add_issue_directly(self):
        """Should add issue using add() method."""
        diag = Diagnostics()
        issue = Issue(Severity.ERROR, "test.error", "Error message")

        diag.add(issue)

        assert len(diag.issues) == 1
        assert diag.issues[0] == issue

    def test_warn_method(self):
        """Should add warning using warn() helper."""
        diag = Diagnostics()

        diag.warn("test.warning", "Warning message")

        assert len(diag.issues) == 1
        assert diag.issues[0].severity == Severity.WARNING
        assert diag.issues[0].code == "test.warning"
        assert diag.issues[0].message == "Warning message"

    def test_error_method(self):
        """Should add error using error() helper."""
        diag = Diagnostics()

        diag.error("test.error", "Error message")

        assert len(diag.issues) == 1
        assert diag.issues[0].severity == Severity.ERROR
        assert diag.issues[0].code == "test.error"

    def test_info_method(self):
        """Should add info using info() helper."""
        diag = Diagnostics()

        diag.info("test.info", "Info message")

        assert len(diag.issues) == 1
        assert diag.issues[0].severity == Severity.INFO

    def test_warn_with_inid(self):
        """Should support inid parameter."""
        diag = Diagnostics()

        diag.warn("test", "message", inid="54")

        assert diag.issues[0].inid == "54"

    def test_warn_with_meta(self):
        """Should support meta kwargs."""
        diag = Diagnostics()

        diag.warn("test", "message", field="title", count=5, data={"key": "value"})

        assert diag.issues[0].meta["field"] == "title"
        assert diag.issues[0].meta["count"] == 5
        assert diag.issues[0].meta["data"] == {"key": "value"}

    def test_multiple_issues(self):
        """Should handle multiple issues."""
        diag = Diagnostics()

        diag.error("e1", "Error 1")
        diag.warn("w1", "Warning 1")
        diag.info("i1", "Info 1")
        diag.error("e2", "Error 2")

        assert len(diag.issues) == 4


class TestDiagnosticsQuerying:
    """Test querying methods on Diagnostics."""

    @pytest.fixture
    def populated_diagnostics(self):
        """Diagnostics instance with various issues."""
        diag = Diagnostics()
        diag.error("error1", "First error")
        diag.error("error2", "Second error")
        diag.warn("warn1", "First warning")
        diag.warn("warn2", "Second warning")
        diag.warn("warn3", "Third warning")
        diag.info("info1", "First info")
        return diag

    def test_errors_returns_only_errors(self, populated_diagnostics):
        """Should return only ERROR issues."""
        errors = list(populated_diagnostics.errors())

        assert len(errors) == 2
        assert all(e.severity == Severity.ERROR for e in errors)

    def test_warnings_returns_only_warnings(self, populated_diagnostics):
        """Should return only WARNING issues."""
        warnings = list(populated_diagnostics.warnings())

        assert len(warnings) == 3
        assert all(w.severity == Severity.WARNING for w in warnings)

    def test_infos_returns_only_infos(self, populated_diagnostics):
        """Should return only INFO issues."""
        infos = list(populated_diagnostics.infos())

        assert len(infos) == 1
        assert all(i.severity == Severity.INFO for i in infos)

    def test_num_errors(self, populated_diagnostics):
        """Should count errors correctly."""
        assert populated_diagnostics.num_errors() == 2

    def test_num_warnings(self, populated_diagnostics):
        """Should count warnings correctly."""
        assert populated_diagnostics.num_warnings() == 3

    def test_num_info(self, populated_diagnostics):
        """Should count info messages correctly."""
        assert populated_diagnostics.num_info() == 1

    def test_ok_when_no_errors(self):
        """Should return True when no errors."""
        diag = Diagnostics()
        diag.warn("w", "Warning")
        diag.info("i", "Info")

        assert diag.ok() is True

    def test_ok_when_has_errors(self):
        """Should return False when has errors."""
        diag = Diagnostics()
        diag.error("e", "Error")
        diag.warn("w", "Warning")

        assert diag.ok() is False

    def test_ok_when_empty(self):
        """Should return True when empty."""
        diag = Diagnostics()
        assert diag.ok() is True

    def test_iter_all_issues(self, populated_diagnostics):
        """Should iterate all issues when no severity filter."""
        all_issues = list(populated_diagnostics.iter())

        assert len(all_issues) == 6

    def test_iter_filtered_by_severity(self, populated_diagnostics):
        """Should filter by severity when specified."""
        errors = list(populated_diagnostics.iter(severity=Severity.ERROR))

        assert len(errors) == 2
        assert all(e.severity == Severity.ERROR for e in errors)


class TestDiagnosticsDeduplicate:
    """Test deduplication functionality."""

    def test_removes_exact_duplicates(self):
        """Should remove exact duplicate issues."""
        diag = Diagnostics()

        diag.error("dup", "Duplicate message")
        diag.error("dup", "Duplicate message")
        diag.error("dup", "Duplicate message")

        diag.deduplicate()

        assert len(diag.issues) == 1

    def test_keeps_first_occurrence(self):
        """Should keep first occurrence of duplicate."""
        diag = Diagnostics()

        diag.error("dup", "Message", first=True)
        diag.error("dup", "Message", second=True)

        diag.deduplicate()

        assert len(diag.issues) == 1
        # Should keep the first one
        assert diag.issues[0].meta.get("first") is True

    def test_different_codes_not_duplicates(self):
        """Should not treat different codes as duplicates."""
        diag = Diagnostics()

        diag.error("code1", "Message")
        diag.error("code2", "Message")

        diag.deduplicate()

        assert len(diag.issues) == 2

    def test_different_messages_not_duplicates(self):
        """Should not treat different messages as duplicates."""
        diag = Diagnostics()

        diag.error("code", "Message 1")
        diag.error("code", "Message 2")

        diag.deduplicate()

        assert len(diag.issues) == 2

    def test_different_severities_not_duplicates(self):
        """Should not treat different severities as duplicates."""
        diag = Diagnostics()

        diag.error("code", "Message")
        diag.warn("code", "Message")

        diag.deduplicate()

        assert len(diag.issues) == 2

    def test_different_inids_not_duplicates(self):
        """Should not treat different INIDs as duplicates."""
        diag = Diagnostics()

        diag.error("code", "Message", inid="54")
        diag.error("code", "Message", inid="57")

        diag.deduplicate()

        assert len(diag.issues) == 2

    def test_meta_not_considered_in_dedup(self):
        """Should not consider meta field in deduplication."""
        diag = Diagnostics()

        diag.error("code", "Message", a=1)
        diag.error("code", "Message", b=2)

        diag.deduplicate()

        # Should be considered duplicates despite different meta
        assert len(diag.issues) == 1

    def test_mixed_duplicates_and_unique(self):
        """Should handle mix of duplicate and unique issues."""
        diag = Diagnostics()

        diag.error("e1", "Error 1")
        diag.error("e1", "Error 1")  # duplicate
        diag.warn("w1", "Warning 1")
        diag.warn("w1", "Warning 1")  # duplicate
        diag.warn("w1", "Warning 1")  # duplicate
        diag.info("i1", "Info 1")     # unique

        diag.deduplicate()

        assert diag.num_errors() == 1
        assert diag.num_warnings() == 1
        assert diag.num_info() == 1


class TestDiagnosticsMerge:
    """Test merging diagnostics."""

    def test_merge_combines_issues(self):
        """Should combine issues from two diagnostics."""
        diag1 = Diagnostics()
        diag1.error("e1", "Error from diag1")
        diag1.warn("w1", "Warning from diag1")

        diag2 = Diagnostics()
        diag2.error("e2", "Error from diag2")
        diag2.info("i2", "Info from diag2")

        diag1.merge(diag2)

        assert len(diag1.issues) == 4
        assert diag1.num_errors() == 2
        assert diag1.num_warnings() == 1
        assert diag1.num_info() == 1

    def test_merge_preserves_order(self):
        """Should preserve order when merging."""
        diag1 = Diagnostics()
        diag1.add(Issue(Severity.ERROR, "e1", "msg1"))
        diag1.add(Issue(Severity.ERROR, "e2", "msg2"))

        diag2 = Diagnostics()
        diag2.add(Issue(Severity.ERROR, "e3", "msg3"))

        diag1.merge(diag2)

        codes = [issue.code for issue in diag1.issues]
        assert codes == ["e1", "e2", "e3"]

    def test_merge_with_empty(self):
        """Should handle merging with empty diagnostics."""
        diag1 = Diagnostics()
        diag1.error("e1", "Error")

        diag2 = Diagnostics()  # empty

        diag1.merge(diag2)

        assert len(diag1.issues) == 1


class TestDiagnosticsEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_diagnostics_ok(self):
        """Empty diagnostics should be OK."""
        diag = Diagnostics()
        assert diag.ok() is True
        assert diag.num_errors() == 0
        assert diag.num_warnings() == 0

    def test_empty_code_and_message(self):
        """Should handle empty code and message strings."""
        diag = Diagnostics()
        diag.error("", "")

        assert len(diag.issues) == 1
        assert diag.issues[0].code == ""
        assert diag.issues[0].message == ""

    def test_very_long_message(self):
        """Should handle very long messages."""
        diag = Diagnostics()
        long_msg = "x" * 10000

        diag.error("test", long_msg)

        assert len(diag.issues) == 1
        assert len(diag.issues[0].message) == 10000

    def test_unicode_in_messages(self):
        """Should handle Unicode in messages."""
        diag = Diagnostics()

        diag.error("test", "Error with emoji 🎉 and 中文")

        assert "🎉" in diag.issues[0].message
        assert "中文" in diag.issues[0].message

    def test_nested_meta_structures(self):
        """Should handle nested structures in meta."""
        diag = Diagnostics()

        diag.error(
            "test",
            "message",
            nested={"deep": {"value": 123}},
            list=[1, 2, 3],
            mixed={"list": [{"key": "value"}]},
        )

        assert diag.issues[0].meta["nested"]["deep"]["value"] == 123
        assert diag.issues[0].meta["list"] == [1, 2, 3]
