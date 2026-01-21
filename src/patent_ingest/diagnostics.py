from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, List, Dict, Generic, TypeVar, Union

T = TypeVar("T")


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Diagnostic:
    severity: Severity
    code: str
    message: str
    meta: Dict[str, Any] = field(default_factory=dict)
    field: Optional[str] = None
    where: Optional[Any] = None  # Span|MultiSpan
    raw: Optional[str] = None  # small excerpt/snippet


@dataclass
class Diagnostics:
    errors: List[Diagnostic] = field(default_factory=list)
    warnings: List[Diagnostic] = field(default_factory=list)
    info: List[Diagnostic] = field(default_factory=list)

    def add(self, d: Diagnostic) -> None:
        if d.severity is Severity.ERROR:
            self.errors.append(d)
        elif d.severity is Severity.WARNING:
            self.warnings.append(d)
        else:
            self.info.append(d)

    def error(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        where: Any | None = None,
        raw: str | None = None,
        **meta: Any,
    ) -> None:
        self.add(
            Diagnostic(
                Severity.ERROR,
                code,
                message,
                field=field,
                where=where,
                raw=raw,
                meta=meta,
            )
        )

    def warn(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        where: Any | None = None,
        raw: str | None = None,
        **meta: Any,
    ) -> None:
        self.add(
            Diagnostic(
                Severity.WARNING,
                code,
                message,
                field=field,
                where=where,
                raw=raw,
                meta=meta,
            )
        )

    def info_msg(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        where: Any | None = None,
        raw: str | None = None,
        **meta: Any,
    ) -> None:
        self.add(
            Diagnostic(
                Severity.INFO,
                code,
                message,
                field=field,
                where=where,
                raw=raw,
                meta=meta,
            )
        )

    def deduplicate(self) -> "Diagnostics":
        """Remove duplicate diagnostics based on code, message, and field.

        Keeps the first occurrence of each unique diagnostic.
        """
        def _dedupe_list(diags: List[Diagnostic]) -> List[Diagnostic]:
            seen = set()
            unique = []
            for d in diags:
                # Create a key based on code, message, and field
                # (ignore where/raw/meta since those can vary for same logical error)
                key = (d.code, d.message, d.field)
                if key not in seen:
                    seen.add(key)
                    unique.append(d)
            return unique

        self.errors = _dedupe_list(self.errors)
        self.warnings = _dedupe_list(self.warnings)
        self.info = _dedupe_list(self.info)
        return self

    def merge(self, other: "Diagnostics") -> "Diagnostics":
        """Merge another Diagnostics object into this one, then deduplicate."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.info.extend(other.info)
        # Deduplicate after merging to avoid duplicate diagnostics
        return self.deduplicate()

    def diagnostics_as(self, fmt: DiagFormat):
        return render_diagnostics(self, fmt)


@dataclass(frozen=True)
class ParseResult(Generic[T]):
    value: Optional[T]
    diag: Diagnostics = field(default_factory=Diagnostics)

    def require(self, field: str) -> T:
        if self.value is None:
            raise ValueError(f"Missing required field: {field}")
        return self.value


# ===========================================
# Formatting utilities
# ===========================================


class DiagFormat(str, Enum):
    TEXT = "text"  # human-readable multiline
    JSON = "json"  # dict suitable for json.dumps
    SUMMARY = "summary"  # compact counts + top codes


def render_diagnostics(
    diag: Diagnostics, fmt: DiagFormat
) -> Union[str, Dict[str, Any]]:
    if fmt is DiagFormat.TEXT:
        return format_diagnostics_text(diag)
    if fmt is DiagFormat.JSON:
        return diagnostics_to_dict(diag)
    if fmt is DiagFormat.SUMMARY:
        return summarize_diagnostics(diag)
    raise ValueError(f"Unknown diagnostics format: {fmt}")


def format_diagnostics_text(diag: Diagnostics) -> str:
    lines: list[str] = []

    def add_one(d: Diagnostic) -> None:
        fld = f"[{d.field}] " if d.field else ""
        loc = f" @ {d.where}" if d.where else ""
        lines.append(f"{d.severity.value.upper()} {fld}{d.code}: {d.message}{loc}")
        if d.raw:
            lines.append(f"  raw: {d.raw!r}")
        if d.meta:
            lines.append(f"  meta: {d.meta}")

    for d in diag.errors:
        add_one(d)
    for d in diag.warnings:
        add_one(d)
    for d in diag.info:
        add_one(d)

    return "\n".join(lines)


def diagnostics_to_dict(diag: Diagnostics) -> dict[str, Any]:
    def one(d: Diagnostic) -> dict[str, Any]:
        return {
            "severity": d.severity.value,
            "code": d.code,
            "message": d.message,
            "field": d.field,
            "raw": d.raw,
            "meta": d.meta,
            "where": where_to_dict(d.where) if d.where else None,
        }

    return {
        "errors": [one(d) for d in diag.errors],
        "warnings": [one(d) for d in diag.warnings],
        "info": [one(d) for d in diag.info],
    }


def summarize_diagnostics(diag: Diagnostics, *, top_n: int = 5) -> dict[str, Any]:
    def key(d: Diagnostic) -> str:
        if d.field:
            return f"{d.field}:{d.code}"
        return d.code

    return {
        "ok": len(diag.errors) == 0,
        "error_count": len(diag.errors),
        "warning_count": len(diag.warnings),
        "info_count": len(diag.info),
        "top_errors": [key(d) for d in diag.errors[:top_n]],
        "top_warnings": [key(d) for d in diag.warnings[:top_n]],
    }


def where_to_dict(where: Any) -> Any:
    # Works for your Span/MultiSpan model
    if where is None:
        return None
    if hasattr(where, "parts"):  # MultiSpan
        return {"type": "multispan", "parts": [where_to_dict(p) for p in where.parts]}
    # Span
    return {
        "type": "span",
        "start": {
            "page": where.start.page,
            "column": where.start.column.value,
            "offset": where.start.offset,
        },
        "end": {
            "page": where.end.page,
            "column": where.end.column.value,
            "offset": where.end.offset,
        },
    }
