from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

import re

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.front_matter.abstract import extract_abstract
from patent_ingest.front_matter.citations import extract_citations, CitationId
from patent_ingest.front_matter.counts import extract_reported_counts, ReportedCounts
from patent_ingest.front_matter.assignee import extract_assignee
from patent_ingest.front_matter.inid import parse_inid_blocks_raw
from patent_ingest.front_matter.inventor import extract_inventors
from patent_ingest.front_matter.grant_date import extract_grant_date, extract_filed_date
from patent_ingest.front_matter.application_number import extract_application_number
from patent_ingest.front_matter.patent_id import extract_patent_id
from patent_ingest.front_matter.title import extract_title
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind
from patent_ingest.patent_id import USPatentId
from typing import Any
from patent_ingest.diagnostics import Diagnostics


@dataclass(frozen=True)
class FrontMatterData:
    inid_blocks: Dict[INIDKind, ParsedRaw[str]]
    patent_id: ParsedNorm[USPatentId] | None = None
    title: ParsedNorm[str] | None = None
    application_number: ParsedNorm[str] | None = None
    filed_date: ParsedNorm[str] | None = None
    grant_date: ParsedNorm[str] | None = None
    assignee: ParsedNorm[str] | None = None
    inventors: List[ParsedNorm[str]] | None = None
    abstract: ParsedNorm[str] | None = None
    reported_counts: ParsedNorm[ReportedCounts] | None = None
    citations: List[ParsedNorm[CitationId]] | None = None
    num_sheets: int = field(init=False)

    def __post_init__(self):
        # Find the last page in a data object in the parsed front matter...
        num_sheets = -1

        if (last_sheet_patent_id := max(self.patent_id.where.pages) + 1) > num_sheets:
            num_sheets = max(num_sheets, last_sheet_patent_id)
        if (last_sheet_title := max(self.title.where.pages) + 1) > num_sheets:
            num_sheets = max(num_sheets, last_sheet_title)
        if (
            last_sheet_application_number := max(self.application_number.where.pages)
            + 1
        ) > num_sheets:
            num_sheets = max(num_sheets, last_sheet_application_number)
        if (last_sheet_filed_date := max(self.filed_date.where.pages) + 1) > num_sheets:
            num_sheets = max(num_sheets, last_sheet_filed_date)
        if (last_sheet_grant_date := max(self.grant_date.where.pages) + 1) > num_sheets:
            num_sheets = max(num_sheets, last_sheet_grant_date)
        if (last_sheet_assignee := max(self.assignee.where.pages) + 1) > num_sheets:
            num_sheets = max(num_sheets, last_sheet_assignee)
        for each in self.inventors:
            if (last_sheet_each := max(each.where.pages) + 1) > num_sheets:
                num_sheets = max(num_sheets, last_sheet_each)
        if (last_sheet_abstract := max(self.abstract.where.pages) + 1) > num_sheets:
            num_sheets = max(num_sheets, last_sheet_abstract)
        if (
            last_sheet_reported_counts := max(self.reported_counts.where.pages) + 1
        ) > num_sheets:
            num_sheets = max(num_sheets, last_sheet_reported_counts)
        for each in self.citations:
            if (last_sheet_each := max(each.where.pages) + 1) > num_sheets:
                num_sheets = max(num_sheets, last_sheet_each)

        assert num_sheets >= 0, "FrontMatterData must have at least one page of data"

        object.__setattr__(self, "num_sheets", num_sheets)

    def canonical(self) -> Dict[str, Any]:
        """
        Produce a stable, test-friendly projection of parse_front_page()/parse_front_matter() output.
        """

        return {
            "patent_number_normalized": self.patent_id.value,
            "title": self.title.value,
            "assignee": self.assignee.value,
            "inventors": [each.value.name for each in self.inventors],
            "application_no": self.application_number.value,
            "filed_iso": self.filed_date.value,
            "grant_iso": self.grant_date.value,
            "reported_claim_count": self.reported_counts.value.reported_claim_count,
            "reported_drawing_sheet_count": self.reported_counts.value.reported_drawing_sheet_count,
            "cited_us_patents_digits": [
                each.value.canonical
                for each in self.citations
                if each.value.type == "US_GRANT"
            ],
            "cited_us_publications": [
                each.value.canonical
                for each in self.citations
                if each.value.type == "US_PUBAPP"
            ],
            "num_sheets": self.num_sheets,
        }


class ParseStatus(str, Enum):
    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class FrontMatterResult:
    status: ParseStatus
    diagnostics: Diagnostics
    data: Optional[FrontMatterData] = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FrontMatter:
    pages: MultiPage

    def parse(
        self,
        diagnostics: Diagnostics,
        sep: str = "\n",
        order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
    ) -> FrontMatterData:
        # try with the inid blocks
        inid_blocks = parse_inid_blocks_raw(self.pages)

        patent_id = extract_patent_id(self.pages, inid_blocks, diagnostics)
        title = extract_title(self.pages, inid_blocks, diagnostics)
        application_number = extract_application_number(
            self.pages, inid_blocks, diagnostics
        )
        grant_date = extract_grant_date(self.pages, inid_blocks, diagnostics)
        filed_date = extract_filed_date(self.pages, inid_blocks, diagnostics)
        assignee = extract_assignee(inid_blocks, diagnostics)
        inventors = extract_inventors(self.pages, inid_blocks, diagnostics)
        abstract = extract_abstract(self.pages, diagnostics)
        reported_counts = extract_reported_counts(self.pages, diagnostics)
        citations = extract_citations(self.pages, diagnostics)

        parsed = FrontMatterData(
            inid_blocks=inid_blocks,
            patent_id=patent_id,
            title=title,
            application_number=application_number,
            grant_date=grant_date,
            filed_date=filed_date,
            assignee=assignee,
            inventors=inventors,
            abstract=abstract,
            reported_counts=reported_counts,
            citations=citations,
        )

        return parsed


@dataclass(frozen=True)
class FrontMatterPolicy:
    required_fields: tuple[str, ...] = ("patent_id",)
    strict_required: bool = False  # if True => missing required => FAILED
    fail_on_catastrophic: bool = True  # typically True


def parse_front_matter(
    doc: MultiPage,
    *,
    policy: FrontMatterPolicy = FrontMatterPolicy(),
) -> FrontMatterResult:
    diag = Diagnostics()

    # Catastrophic: empty / unusable doc
    if not doc.pages or all(
        (not (p.left or "").strip() and not (p.right or "").strip()) for p in doc.pages
    ):
        diag.error(
            "front_matter.empty_document",
            "Document contains no usable text.",
            field="document",
        )
        return FrontMatterResult(status=ParseStatus.FAILED, data=None, diagnostics=diag)

    # Start by finding out the expected number of drawing sheets
    reported_drawing_sheet_count = extract_reported_counts(
        doc, diag
    ).value.reported_drawing_sheet_count
    drawing_sheet_start_index = infer_drawings_start_index(
        doc, reported_drawing_sheet_count=reported_drawing_sheet_count, diag=diag
    )
    if drawing_sheet_start_index is None:
        diag.error(
            "front_matter.infer_drawings_start_index_failed",
            "Failed to infer drawings start index.",
            field="document",
        )
        return FrontMatterResult(status=ParseStatus.FAILED, data=None, diagnostics=diag)

    front_matter = FrontMatter(doc.subset(pages=range(0, drawing_sheet_start_index)))
    data = front_matter.parse(diag)

    # Required fields check (policy)
    missing_required = []
    for f in policy.required_fields:
        v = getattr(data, f, None)
        if v is None or (isinstance(v, list) and not v):
            missing_required.append(f)
            diag.error("required.missing", f"Required field missing: {f}", field=f)

    # Decide status
    if diag.errors:
        # if errors include catastrophic codes, already returned above
        status = (
            ParseStatus.FAILED
            if (policy.strict_required and missing_required)
            else ParseStatus.PARTIAL
        )
    else:
        status = ParseStatus.OK

    return FrontMatterResult(status=status, data=data, diagnostics=diag)

    # Parse


def infer_drawings_start_index(
    doc: MultiPage, reported_drawing_sheet_count: int, diag: Diagnostics
) -> Optional[int]:
    s = infer_drawings_start_index_by_sheet_header(
        doc,
        reported_drawing_sheet_count,
        search_start=1,
        search_limit=len(doc) - 1,
    )
    return s


SHEET_OF_N_PAT = re.compile(
    r"\s*(\d{1,3})\s*\bof\b\s*(\d{1,3})\b",
    re.IGNORECASE,
)


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def infer_drawings_start_index_by_sheet_header(
    doc: MultiPage,
    expected_sheets: int,
    *,
    search_start: int = 1,
    search_limit: int = 25,
) -> Optional[int]:
    """
    Prefer explicit 'Sheet i of n' markers to locate the drawings block.
    Assumes drawings sheets are consecutive pages once started.
    """
    n_pages = len(doc)
    if expected_sheets <= 0 or n_pages <= 1:
        return None

    # Scan a bounded range
    stop = min(n_pages, search_start + search_limit)

    sheet_hits: List[Tuple[int, int, int]] = []  # (page_index, i, n)
    for idx in range(search_start, stop):
        left = normalize_ws(doc.get_column_text(idx, Column.LEFT))
        right = normalize_ws(doc.get_column_text(idx, Column.RIGHT))
        for each in [left, right]:
            m = SHEET_OF_N_PAT.search(each)
            if m:
                i = int(m.group(1))
                n = int(m.group(2))
                sheet_hits.append((idx, i, n))
                continue

    if not sheet_hits:
        return None

    # Choose the earliest hit that is consistent with expected_sheets if available
    # (Some patents print "Sheet 1 of N". Prefer those.)
    for idx, i, n in sheet_hits:
        if i == 1 and (n == expected_sheets or expected_sheets is None):
            return idx

    # Otherwise choose earliest hit with n == expected_sheets
    for idx, i, n in sheet_hits:
        if n == expected_sheets:
            return idx

    # Fallback: earliest hit
    return sheet_hits[0][0]
