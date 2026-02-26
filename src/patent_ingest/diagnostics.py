from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union, Iterable

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(config=ConfigDict(frozen=True))
class Issue:
    severity: Severity
    code: str
    message: str
    inid: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


@dataclass(config=ConfigDict(arbitrary_types_allowed=True))
class Diagnostics:
    issues: List[Issue] = Field(default_factory=list)

    # ---- construction helpers ----
    def add(self, i: Issue) -> None:
        self.issues.append(i)

    def warn(
        self, code: str, msg: str, *, inid: str | None = None, **meta: Any
    ) -> None:
        self.issues.append(
            Issue(
                code=code, message=msg, severity=Severity.WARNING, inid=inid, meta=meta
            )
        )

    def error(
        self, code: str, msg: str, *, inid: str | None = None, **meta: Any
    ) -> None:
        self.issues.append(
            Issue(code=code, message=msg, severity=Severity.ERROR, inid=inid, meta=meta)
        )

    def info(
        self, code: str, msg: str, *, inid: str | None = None, **meta: Any
    ) -> None:
        self.issues.append(
            Issue(code=code, message=msg, severity=Severity.INFO, inid=inid, meta=meta)
        )

    # ---- querying ----
    def iter(self, *, severity: Severity | None = None) -> Iterable[Issue]:
        if severity is None:
            yield from self.issues
            return
        for i in self.issues:
            if i.severity == severity:
                yield i

    def errors(self) -> Iterable[Issue]:
        return self.iter(severity=Severity.ERROR)

    def warnings(self) -> Iterable[Issue]:
        return self.iter(severity=Severity.WARNING)

    def infos(self) -> Iterable[Issue]:
        return self.iter(severity=Severity.INFO)

    def num_errors(self) -> int:
        return sum(1 for _ in self.errors())

    def num_warnings(self) -> int:
        return sum(1 for _ in self.warnings())

    def num_info(self) -> int:
        return sum(1 for _ in self.infos())

    def ok(self) -> bool:
        return not any(True for _ in self.errors())

    # ---- transforms ----
    def deduplicate(self) -> "Diagnostics":
        """
        Remove duplicates based on (severity, code, message, inid).
        Keeps the first occurrence of each unique diagnostic.
        """
        seen: set[tuple[str, str, str, Optional[str]]] = set()
        unique: list[Issue] = []
        for d in self.issues:
            key = (d.severity.value, d.code, d.message, d.inid)
            if key in seen:
                continue
            seen.add(key)
            unique.append(d)
        self.issues = unique
        return self

    def merge(self, other: "Diagnostics") -> "Diagnostics":
        self.issues.extend(other.issues)
        return self.deduplicate()

    # ---- formatting ----
    def as_(self, fmt: "DiagFormat") -> Union[str, Dict[str, Any]]:
        return render_diagnostics(self, fmt)


class DiagnosticsError(RuntimeError):
    pass


def raise_if_errors(diag: Diagnostics, *, prefix: str = "") -> None:
    errs = list(diag.errors())
    if not errs:
        return
    msg = format_diagnostics_text(Diagnostics(issues=errs))
    raise DiagnosticsError(prefix + msg)


class DiagFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    SUMMARY = "summary"


def render_diagnostics(
    diag: Diagnostics, fmt: DiagFormat
) -> Union[str, Dict[str, Any]]:
    if fmt == DiagFormat.TEXT:
        return format_diagnostics_text(diag)
    if fmt == DiagFormat.JSON:
        return diagnostics_to_dict(diag)
    if fmt == DiagFormat.SUMMARY:
        return summarize_diagnostics(diag)
    raise ValueError(f"Unknown diagnostics format: {fmt}")


def format_diagnostics_text(diag: Diagnostics) -> str:
    lines: list[str] = []

    def add_one(i: Issue) -> None:
        where = f" (inid={i.inid})" if i.inid else ""
        lines.append(f"{i.severity.value.upper()} {i.code}{where}: {i.message}")
        if i.meta:
            lines.append(f"  meta: {i.meta}")

    for i in diag.errors():
        add_one(i)
    for i in diag.warnings():
        add_one(i)
    for i in diag.infos():
        add_one(i)

    return "\n".join(lines)


def diagnostics_to_dict(diag: Diagnostics) -> dict[str, Any]:
    def one(i: Issue) -> dict[str, Any]:
        return {
            "severity": i.severity.value,
            "code": i.code,
            "message": i.message,
            "inid": i.inid,
            "meta": i.meta,
        }

    return {
        "errors": [one(i) for i in diag.errors()],
        "warnings": [one(i) for i in diag.warnings()],
        "info": [one(i) for i in diag.infos()],
    }


def summarize_diagnostics(diag: Diagnostics, *, top_n: int = 5) -> dict[str, Any]:
    errors = list(diag.errors())
    warnings = list(diag.warnings())
    infos = list(diag.infos())

    def top_codes(items: list[Issue]) -> list[str]:
        # stable: keep first appearance order
        seen: set[str] = set()
        out: list[str] = []
        for it in items:
            if it.code in seen:
                continue
            seen.add(it.code)
            out.append(it.code)
            if len(out) >= top_n:
                break
        return out

    return {
        "ok": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(infos),
        "top_errors": top_codes(errors),
        "top_warnings": top_codes(warnings),
    }


def _canon_diagnostics(diag: Diagnostics) -> Dict[str, Any]:
    # You already have a renderer; use it if present. Otherwise make minimal JSON.
    if hasattr(diag, "diagnostics_as"):
        try:
            return diag.diagnostics_as(DiagFormat.JSON)  # if your renderer expects enum
        except Exception:
            pass

    def one(i: Any) -> Dict[str, Any]:
        return {
            "severity": getattr(i.severity, "value", str(i.severity)),
            "code": i.code,
            "message": i.message,
            "inid": getattr(i, "inid", None),
            "meta": getattr(i, "meta", {}) or {},
        }

    return {
        "errors": [one(i) for i in diag.errors()],
        "warnings": [one(i) for i in diag.warnings()],
        "info": [one(i) for i in diag.infos()],
    }
