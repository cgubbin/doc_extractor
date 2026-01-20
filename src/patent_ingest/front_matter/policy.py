from dataclasses import dataclass
from patent_ingest.diagnostics import Diagnostics, format_diagnostics
from patent_ingest.front_matter.model import FrontMatterResult


@dataclass(frozen=True)
class ParsePolicy:
    required_fields: tuple[str, ...] = ("patent_id", "application_number")
    fail_on_error: bool = True
    treat_warnings_as_errors: bool = False


def enforce_policy(result: FrontMatterResult, policy: ParsePolicy) -> FrontMatterResult:
    diag = result.diagnostics

    # Promote warnings to errors if desired
    if policy.treat_warnings_as_errors and diag.warnings:
        for w in diag.warnings:
            diag.errors.append(w)  # or clone with Severity.ERROR
        diag.warnings.clear()

    # Missing required fields => error
    for f in policy.required_fields:
        if getattr(result.data, f) is None or (
            isinstance(getattr(result.data, f), list) and not getattr(result.data, f)
        ):
            diag.error("required.missing", f"Required field missing: {f}", field=f)

    if policy.fail_on_error and diag.errors:
        raise ParseFailed(diag)

    return result


class ParseFailed(Exception):
    def __init__(self, diagnostics: Diagnostics):
        self.diagnostics = diagnostics
        super().__init__(format_diagnostics(diagnostics))
