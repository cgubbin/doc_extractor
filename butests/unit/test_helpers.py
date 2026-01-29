"""Test helper functions and assertion utilities.

This module provides utilities for comparing parsed results, asserting on
diagnostics, and other common test operations.
"""

from typing import Any, Callable
from patent_ingest.diagnostics import Diagnostics


# ==================== Diagnostic Assertions ====================

def assert_no_errors(diag: Diagnostics, msg: str = "Expected no errors"):
    """Assert that diagnostics contain no errors."""
    if diag.errors:
        error_msgs = "\n  ".join(f"{e.code}: {e.message}" for e in diag.errors)
        raise AssertionError(f"{msg}\nErrors found:\n  {error_msgs}")


def assert_no_warnings(diag: Diagnostics, msg: str = "Expected no warnings"):
    """Assert that diagnostics contain no warnings."""
    if diag.warnings:
        warning_msgs = "\n  ".join(f"{w.code}: {w.message}" for w in diag.warnings)
        raise AssertionError(f"{msg}\nWarnings found:\n  {warning_msgs}")


def assert_no_diagnostics(diag: Diagnostics, msg: str = "Expected no diagnostics"):
    """Assert that diagnostics are completely empty."""
    assert_no_errors(diag, msg)
    assert_no_warnings(diag, msg)


def assert_has_error(diag: Diagnostics, error_code: str, msg: str = None):
    """Assert that diagnostics contain a specific error code."""
    error_codes = [e.code for e in diag.errors]
    if error_code not in error_codes:
        msg = msg or f"Expected error code '{error_code}'"
        raise AssertionError(f"{msg}\nFound error codes: {error_codes}")


def assert_has_warning(diag: Diagnostics, warning_code: str, msg: str = None):
    """Assert that diagnostics contain a specific warning code."""
    warning_codes = [w.code for w in diag.warnings]
    if warning_code not in warning_codes:
        msg = msg or f"Expected warning code '{warning_code}'"
        raise AssertionError(f"{msg}\nFound warning codes: {warning_codes}")


def get_diag_codes(diag: Diagnostics) -> dict[str, list[str]]:
    """Extract diagnostic codes as a dict for easy comparison.

    Returns:
        Dict with keys: errors, warnings, info
    """
    return {
        "errors": [d.code for d in diag.errors],
        "warnings": [d.code for d in diag.warnings],
        "info": [d.code for d in diag.info],
    }


# ==================== Text Comparison Utilities ====================

def normalize_whitespace(text: str) -> str:
    """Normalize whitespace for comparison (collapse to single spaces)."""
    return " ".join((text or "").split())


def assert_text_equals(actual: str, expected: str, normalize: bool = True):
    """Assert that two text strings are equal, optionally normalizing whitespace.

    Args:
        actual: Actual text
        expected: Expected text
        normalize: Whether to normalize whitespace before comparison
    """
    if normalize:
        actual = normalize_whitespace(actual)
        expected = normalize_whitespace(expected)

    if actual != expected:
        raise AssertionError(
            f"Text mismatch:\n"
            f"Expected: {expected[:100]}{'...' if len(expected) > 100 else ''}\n"
            f"Actual:   {actual[:100]}{'...' if len(actual) > 100 else ''}"
        )


def assert_text_contains(text: str, substring: str, normalize: bool = True):
    """Assert that text contains a substring.

    Args:
        text: Text to search in
        substring: Substring to find
        normalize: Whether to normalize whitespace before comparison
    """
    if normalize:
        text = normalize_whitespace(text)
        substring = normalize_whitespace(substring)

    if substring not in text:
        raise AssertionError(
            f"Substring not found in text.\n"
            f"Looking for: {substring[:100]}{'...' if len(substring) > 100 else ''}\n"
            f"In text:     {text[:100]}{'...' if len(text) > 100 else ''}"
        )


def assert_text_matches_pattern(text: str, pattern: str):
    """Assert that text matches a regex pattern.

    Args:
        text: Text to match
        pattern: Regex pattern
    """
    import re

    if not re.search(pattern, text):
        raise AssertionError(
            f"Text does not match pattern.\n"
            f"Pattern: {pattern}\n"
            f"Text:    {text[:200]}{'...' if len(text) > 200 else ''}"
        )


# ==================== List/Collection Assertions ====================

def assert_lists_equal(actual: list, expected: list, msg: str = None):
    """Assert that two lists are equal with a helpful error message."""
    if actual != expected:
        msg_prefix = f"{msg}\n" if msg else ""
        raise AssertionError(
            f"{msg_prefix}Lists are not equal.\n"
            f"Expected ({len(expected)} items): {expected}\n"
            f"Actual   ({len(actual)} items): {actual}\n"
            f"Missing: {set(expected) - set(actual)}\n"
            f"Extra:   {set(actual) - set(expected)}"
        )


def assert_contains_all(actual: list, expected_items: list, msg: str = None):
    """Assert that actual list contains all expected items."""
    missing = set(expected_items) - set(actual)
    if missing:
        msg_prefix = f"{msg}\n" if msg else ""
        raise AssertionError(
            f"{msg_prefix}Missing expected items: {missing}\n"
            f"Actual list: {actual}"
        )


def assert_length(collection, expected_length: int, msg: str = None):
    """Assert that a collection has the expected length."""
    actual_length = len(collection)
    if actual_length != expected_length:
        msg_prefix = f"{msg}\n" if msg else ""
        raise AssertionError(
            f"{msg_prefix}Length mismatch.\n"
            f"Expected: {expected_length}\n"
            f"Actual:   {actual_length}\n"
            f"Collection: {collection}"
        )


# ==================== Span/Where Assertions ====================

def assert_span_text(doc, span, expected_text: str, normalize: bool = True):
    """Assert that a span extracts to the expected text.

    Args:
        doc: Document object with slice_span or slice_where method
        span: Span or Where object
        expected_text: Expected extracted text
        normalize: Whether to normalize whitespace
    """
    if hasattr(span, "parts"):  # Where object
        actual_text = doc.slice_where(span)
    else:  # Span object
        actual_text = doc.slice_span(span)

    assert_text_equals(actual_text, expected_text, normalize=normalize)


# ==================== Field Value Assertions ====================

def assert_field_value(field, expected_value: str, normalize: bool = True):
    """Assert that a parsed field has the expected value.

    Works with field objects that have a .value attribute.

    Args:
        field: Field object with .value attribute
        expected_value: Expected value
        normalize: Whether to normalize whitespace
    """
    actual_value = field.value if hasattr(field, "value") else str(field)
    assert_text_equals(actual_value, expected_value, normalize=normalize)


def assert_field_empty(field, msg: str = None):
    """Assert that a field is empty (None, empty string, or empty list)."""
    value = field.value if hasattr(field, "value") else field

    is_empty = (
        value is None
        or value == ""
        or (isinstance(value, list) and len(value) == 0)
    )

    if not is_empty:
        msg_prefix = f"{msg}\n" if msg else ""
        raise AssertionError(f"{msg_prefix}Expected empty field but got: {value}")


def assert_field_not_empty(field, msg: str = None):
    """Assert that a field is not empty."""
    value = field.value if hasattr(field, "value") else field

    is_empty = (
        value is None
        or value == ""
        or (isinstance(value, list) and len(value) == 0)
    )

    if is_empty:
        msg_prefix = f"{msg}\n" if msg else ""
        raise AssertionError(f"{msg_prefix}Expected non-empty field")


# ==================== Number/Range Assertions ====================

def assert_in_range(value, min_val, max_val, msg: str = None):
    """Assert that a value is within a range (inclusive)."""
    if not (min_val <= value <= max_val):
        msg_prefix = f"{msg}\n" if msg else ""
        raise AssertionError(
            f"{msg_prefix}Value {value} not in range [{min_val}, {max_val}]"
        )


# ==================== Dict/JSON Comparison ====================

def assert_dict_subset(actual: dict, expected_subset: dict, msg: str = None):
    """Assert that actual dict contains all keys/values from expected_subset.

    Args:
        actual: Actual dictionary
        expected_subset: Expected subset of keys/values
        msg: Optional message prefix
    """
    for key, expected_value in expected_subset.items():
        if key not in actual:
            msg_prefix = f"{msg}\n" if msg else ""
            raise AssertionError(
                f"{msg_prefix}Missing key '{key}' in actual dict.\n"
                f"Actual keys: {list(actual.keys())}"
            )

        actual_value = actual[key]
        if actual_value != expected_value:
            msg_prefix = f"{msg}\n" if msg else ""
            raise AssertionError(
                f"{msg_prefix}Value mismatch for key '{key}'.\n"
                f"Expected: {expected_value}\n"
                f"Actual:   {actual_value}"
            )


# ==================== Custom Comparison ====================

def assert_custom(actual, expected, comparator: Callable[[Any, Any], bool], msg: str = None):
    """Assert using a custom comparison function.

    Args:
        actual: Actual value
        expected: Expected value
        comparator: Function that returns True if values match
        msg: Optional message
    """
    if not comparator(actual, expected):
        msg_prefix = f"{msg}\n" if msg else ""
        raise AssertionError(
            f"{msg_prefix}Comparison failed.\n"
            f"Expected: {expected}\n"
            f"Actual:   {actual}"
        )
