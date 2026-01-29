"""Pytest configuration and fixtures for unit tests."""

import pytest

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column, Span, Where
from patent_ingest.diagnostics import Diagnostics

# Import helper functions to make them easily available in tests
from test_helpers import (
    assert_no_errors,
    assert_no_warnings,
    assert_no_diagnostics,
    assert_has_error,
    assert_has_warning,
    get_diag_codes,
    normalize_whitespace,
    assert_text_equals,
    assert_text_contains,
    assert_lists_equal,
    assert_field_value,
)


@pytest.fixture
def norm_ws():
    # small helper so snippets are readable
    def _norm(s: str) -> str:
        return " ".join((s or "").split())

    return _norm


SEP = "\n"
ORDER = (Column.LEFT, Column.RIGHT)


class TwoColumnMock:
    left: str
    right: str

    def __init__(self, left: str, right: str):
        self.left = left
        self.right = right

    def linearize(self) -> list[str]:
        return self.left + "\n" + self.right


class MultiPageMock:
    pages: list[TwoColumnMock]

    def __init__(
        self,
        pages: list[TwoColumnMock],
    ) -> "MultiPage":
        self.pages = pages

    def __len__(self) -> int:
        return len(self.pages)

    def get_column_text(self, page: int, column: Column) -> str:
        p = self.pages[page]
        return p.left if column is Column.LEFT else p.right

    def slice_span(self, span: Span) -> str:
        txt = self.get_column_text(span.start.page, span.start.column)
        return txt[span.start.offset : span.end.offset]

    def slice_where(self, where: Where, *, joiner: str = "") -> str:
        if isinstance(where, Span):
            return self.slice_span(where)
        return joiner.join(self.slice_span(s) for s in where.parts)

    def subset(self, pages: range) -> "MultiPage":
        mp = MultiPage.__new__(MultiPage)
        mp.pages = [self.pages[i] for i in pages]
        return mp

    def linearize(self) -> str:
        return "\n".join(p.linearize() for p in self.pages)


def mp(*pages: tuple[str, str]) -> MultiPage:
    """mp((left,right), (left,right), ...)"""
    return MultiPageMock(pages=[TwoColumnMock(left=l, right=r) for (l, r) in pages])


@pytest.fixture
def diag() -> Diagnostics:
    return Diagnostics()


@pytest.fixture
def linconf():
    return {"sep": SEP, "order": ORDER}


def diag_codes(diag):
    return {
        "errors": [d.code for d in diag.errors],
        "warnings": [d.code for d in diag.warnings],
        "info": [d.code for d in diag.info],
    }
