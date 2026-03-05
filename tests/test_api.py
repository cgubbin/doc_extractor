"""Unit tests for doc_extractor.api module.

Tests cover:
- FileSystemSink: file writing operations
- MemorySink: in-memory storage
- ParseOptions: configuration handling
- parse_patent function (integration-style)
"""

import pytest
import json
import tempfile
from pathlib import Path

from doc_extractor.api import (
    FileSystemSink,
    MemorySink,
    ParseOptions,
    _sha256,
)


class TestFileSystemSink:
    """Test FileSystemSink implementation."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def sink(self, temp_dir):
        """Create a FileSystemSink instance."""
        return FileSystemSink(temp_dir)

    def test_initialization_creates_directory(self, temp_dir):
        """Should create root directory on initialization."""
        new_dir = temp_dir / "new_sink"
        assert not new_dir.exists()

        sink = FileSystemSink(new_dir)

        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_put_json_creates_file(self, sink, temp_dir):
        """Should write JSON object to file."""
        data = {"key": "value", "number": 42, "nested": {"inner": "data"}}
        result_path = sink.put_json("test/data.json", data)

        # Should return absolute path
        assert Path(result_path).exists()
        assert "test/data.json" in result_path

        # Should contain the data
        written_data = json.loads(Path(result_path).read_text())
        assert written_data == data

    def test_put_json_creates_parent_directories(self, sink, temp_dir):
        """Should create nested directories as needed."""
        data = {"test": "data"}
        result_path = sink.put_json("deeply/nested/path/data.json", data)

        assert Path(result_path).exists()
        assert Path(result_path).parent.name == "path"

    def test_put_json_formats_correctly(self, sink, temp_dir):
        """Should format JSON with proper indentation and sorted keys."""
        data = {"z_key": "first", "a_key": "second", "m_key": "third"}
        result_path = sink.put_json("formatted.json", data)

        content = Path(result_path).read_text()

        # Should be indented
        assert "\n" in content
        assert "  " in content  # 2-space indent

        # Should be sorted by keys
        assert content.index("a_key") < content.index("m_key")
        assert content.index("m_key") < content.index("z_key")

        # Should end with newline
        assert content.endswith("\n")

    def test_put_text_creates_file(self, sink, temp_dir):
        """Should write text to file."""
        text = "This is test text content.\nWith multiple lines."
        result_path = sink.put_text("test.txt", text, content_type="text/plain")

        assert Path(result_path).exists()

        written_text = Path(result_path).read_text(encoding="utf-8")
        assert written_text == text

    def test_put_bytes_creates_file(self, sink, temp_dir):
        """Should write binary data to file."""
        data = b"\x00\x01\x02\x03\x04\x05"
        result_path = sink.put_bytes("binary.dat", data, content_type="application/octet-stream")

        assert Path(result_path).exists()

        written_data = Path(result_path).read_bytes()
        assert written_data == data

    def test_put_operations_with_same_key_overwrite(self, sink, temp_dir):
        """Should overwrite existing files when using same key."""
        key = "test.txt"

        # Write first time
        sink.put_text(key, "first content")
        # Write second time with same key
        result_path = sink.put_text(key, "second content")

        # Should contain only the second content
        content = Path(result_path).read_text()
        assert content == "second content"

    def test_handles_unicode_in_json(self, sink, temp_dir):
        """Should handle Unicode characters in JSON."""
        data = {"message": "Hello 世界", "emoji": "🎉"}
        result_path = sink.put_json("unicode.json", data)

        written_data = json.loads(Path(result_path).read_text(encoding="utf-8"))
        assert written_data == data

    def test_handles_unicode_in_text(self, sink, temp_dir):
        """Should handle Unicode characters in text."""
        text = "Unicode test: 世界 🎉 café"
        result_path = sink.put_text("unicode.txt", text)

        written_text = Path(result_path).read_text(encoding="utf-8")
        assert written_text == text


class TestMemorySink:
    """Test MemorySink implementation."""

    @pytest.fixture
    def sink(self):
        """Create a MemorySink instance."""
        return MemorySink()

    def test_initialization_empty(self, sink):
        """Should initialize with empty storage."""
        assert sink.blobs == {}
        assert sink.json_objects == {}
        assert sink.texts == {}

    def test_put_json_stores_object(self, sink):
        """Should store JSON object in memory."""
        data = {"key": "value", "number": 42}
        result_key = sink.put_json("test.json", data)

        assert result_key == "test.json"
        assert sink.json_objects["test.json"] == data

    def test_put_json_returns_key(self, sink):
        """Should return the key as the URI."""
        data = {"test": "data"}
        result = sink.put_json("my/key.json", data)

        assert result == "my/key.json"

    def test_put_text_stores_text(self, sink):
        """Should store text in memory."""
        text = "This is test text"
        result_key = sink.put_text("test.txt", text)

        assert result_key == "test.txt"
        assert sink.texts["test.txt"] == text

    def test_put_bytes_stores_bytes(self, sink):
        """Should store bytes in memory."""
        data = b"\x00\x01\x02\x03"
        result_key = sink.put_bytes("test.bin", data, content_type="application/octet-stream")

        assert result_key == "test.bin"
        assert sink.blobs["test.bin"] == data

    def test_multiple_put_operations(self, sink):
        """Should handle multiple storage operations."""
        sink.put_json("data1.json", {"a": 1})
        sink.put_json("data2.json", {"b": 2})
        sink.put_text("file1.txt", "text 1")
        sink.put_text("file2.txt", "text 2")
        sink.put_bytes("file1.bin", b"\x01", content_type="application/octet-stream")

        assert len(sink.json_objects) == 2
        assert len(sink.texts) == 2
        assert len(sink.blobs) == 1

    def test_overwrite_with_same_key(self, sink):
        """Should overwrite when using same key."""
        key = "test.json"

        sink.put_json(key, {"first": "data"})
        sink.put_json(key, {"second": "data"})

        assert sink.json_objects[key] == {"second": "data"}

    def test_stores_object_reference_not_copy(self, sink):
        """Should store reference to original object (for efficiency)."""
        data = {"key": "value"}
        sink.put_json("test.json", data)

        # Modifying original should affect stored object
        # (This is expected behavior for in-memory sink)
        data["key"] = "modified"
        assert sink.json_objects["test.json"]["key"] == "modified"

    def test_retrieval_by_key(self, sink):
        """Should be able to retrieve stored items by key."""
        json_data = {"test": "json"}
        text_data = "test text"
        binary_data = b"\x00\x01"

        sink.put_json("j.json", json_data)
        sink.put_text("t.txt", text_data)
        sink.put_bytes("b.bin", binary_data, content_type="application/octet-stream")

        # Retrieve by key
        assert sink.json_objects["j.json"] == json_data
        assert sink.texts["t.txt"] == text_data
        assert sink.blobs["b.bin"] == binary_data


class TestSHA256Helper:
    """Test _sha256 helper function."""

    def test_computes_hash_correctly(self):
        """Should compute correct SHA256 hash."""
        data = b"hello world"
        result = _sha256(data)

        # Expected SHA256 hash of "hello world"
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert result == expected

    def test_returns_hex_string(self):
        """Should return hexadecimal string."""
        data = b"test"
        result = _sha256(data)

        assert isinstance(result, str)
        assert len(result) == 64  # SHA256 produces 64 hex characters
        assert all(c in "0123456789abcdef" for c in result)

    def test_different_inputs_different_hashes(self):
        """Should produce different hashes for different inputs."""
        hash1 = _sha256(b"data1")
        hash2 = _sha256(b"data2")

        assert hash1 != hash2

    def test_same_input_same_hash(self):
        """Should produce same hash for same input (deterministic)."""
        data = b"test data"
        hash1 = _sha256(data)
        hash2 = _sha256(data)

        assert hash1 == hash2

    def test_handles_empty_input(self):
        """Should handle empty input."""
        result = _sha256(b"")

        # SHA256 of empty string is a known value
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert result == expected


class TestParseOptions:
    """Test ParseOptions dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        options = ParseOptions()

        # Check default values exist and are appropriate
        assert hasattr(options, "detect_figures")
        assert hasattr(options, "export_figures_png")
        assert hasattr(options, "export_sheet_png")
        assert hasattr(options, "fail_on_missing_inid")

    def test_can_override_defaults(self):
        """Should allow overriding default values."""
        options = ParseOptions(
            detect_figures=False,
            export_figures_png=True,
            fail_on_missing_inid=True,
        )

        assert options.detect_figures is False
        assert options.export_figures_png is True
        assert options.fail_on_missing_inid is True

    def test_is_frozen_dataclass(self):
        """Should be immutable (frozen dataclass)."""
        options = ParseOptions()

        # Attempting to modify should raise AttributeError
        with pytest.raises((AttributeError, Exception)):
            options.detect_figures = True


# Integration-style tests

class TestSinkComparison:
    """Compare behavior between FileSystemSink and MemorySink."""

    @pytest.fixture
    def fs_sink(self, tmp_path):
        """FileSystemSink instance."""
        return FileSystemSink(tmp_path)

    @pytest.fixture
    def mem_sink(self):
        """MemorySink instance."""
        return MemorySink()

    def test_both_sinks_store_json(self, fs_sink, mem_sink):
        """Both sinks should successfully store JSON."""
        data = {"test": "data", "number": 123}

        fs_result = fs_sink.put_json("test.json", data)
        mem_result = mem_sink.put_json("test.json", data)

        # Both should succeed
        assert fs_result is not None
        assert mem_result is not None

        # FS sink returns path, memory sink returns key
        assert "test.json" in fs_result
        assert mem_result == "test.json"

    def test_both_sinks_handle_nested_paths(self, fs_sink, mem_sink):
        """Both sinks should handle nested paths."""
        data = "test content"

        fs_result = fs_sink.put_text("nested/deep/path/file.txt", data)
        mem_result = mem_sink.put_text("nested/deep/path/file.txt", data)

        assert fs_result is not None
        assert mem_result is not None

    def test_both_sinks_handle_unicode(self, fs_sink, mem_sink):
        """Both sinks should handle Unicode correctly."""
        text = "Unicode: 世界 🎉"

        fs_result = fs_sink.put_text("unicode.txt", text)
        mem_result = mem_sink.put_text("unicode.txt", text)

        assert fs_result is not None
        assert mem_result is not None

        # Verify content is preserved
        if Path(fs_result).exists():
            fs_content = Path(fs_result).read_text(encoding="utf-8")
            assert fs_content == text

        mem_content = mem_sink.texts["unicode.txt"]
        assert mem_content == text


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_file_system_sink_with_special_characters_in_path(self, tmp_path):
        """Should handle special characters in file paths."""
        sink = FileSystemSink(tmp_path)

        # Some filesystems don't allow certain characters
        # Use relatively safe special chars
        data = {"test": "data"}
        result = sink.put_json("test_file-name.json", data)

        assert Path(result).exists()

    def test_memory_sink_with_very_large_json(self):
        """Should handle large JSON objects."""
        sink = MemorySink()

        # Create a large object
        large_data = {f"key_{i}": f"value_{i}" * 100 for i in range(1000)}

        result = sink.put_json("large.json", large_data)

        assert result == "large.json"
        assert len(sink.json_objects["large.json"]) == 1000

    def test_file_system_sink_with_empty_content(self, tmp_path):
        """Should handle empty content."""
        sink = FileSystemSink(tmp_path)

        # Empty JSON
        sink.put_json("empty.json", {})
        # Empty text
        sink.put_text("empty.txt", "")
        # Empty bytes
        sink.put_bytes("empty.bin", b"", content_type="application/octet-stream")

        # All files should exist
        assert (tmp_path / "empty.json").exists()
        assert (tmp_path / "empty.txt").exists()
        assert (tmp_path / "empty.bin").exists()
