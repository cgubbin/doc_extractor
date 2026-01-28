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
from patent_ingest.front_matter.document_type import (
    DocumentType,
    detect_document_type,
    extract_pct_application_number,
    extract_pct_filed_date,
    extract_s371_date,
)
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind
from patent_ingest.patent_id import USPatentId
from typing import Any
from patent_ingest.diagnostics import Diagnostics


@dataclass(frozen=True)
class FrontMatterData:
    inid_blocks: Dict[INIDKind, ParsedRaw[str]]
    document_type: DocumentType = DocumentType.UNKNOWN
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
    s371_date: ParsedNorm[str] | None = None  # US entry date for PCT
    num_sheets: int = field(init=False)

    def __post_init__(self):
        # Find the last page in a data object in the parsed front matter...
        num_sheets = -1

        if (
            self.patent_id
            and (last_sheet_patent_id := max(self.patent_id.where.pages) + 1)
            > num_sheets
        ):
            num_sheets = max(num_sheets, last_sheet_patent_id)
        if (
            self.title
            and (last_sheet_title := max(self.title.where.pages) + 1) > num_sheets
        ):
            num_sheets = max(num_sheets, last_sheet_title)
        if (
            self.application_number
            and (
                last_sheet_application_number := max(
                    self.application_number.where.pages
                )
                + 1
            )
            > num_sheets
        ):
            num_sheets = max(num_sheets, last_sheet_application_number)
        if (
            self.filed_date
            and (last_sheet_filed_date := max(self.filed_date.where.pages) + 1)
            > num_sheets
        ):
            num_sheets = max(num_sheets, last_sheet_filed_date)
        if (
            self.grant_date
            and (last_sheet_grant_date := max(self.grant_date.where.pages) + 1)
            > num_sheets
        ):
            num_sheets = max(num_sheets, last_sheet_grant_date)
        if (
            self.assignee
            and (last_sheet_assignee := max(self.assignee.where.pages) + 1) > num_sheets
        ):
            num_sheets = max(num_sheets, last_sheet_assignee)
        if self.inventors:
            for each in self.inventors:
                if (last_sheet_each := max(each.where.pages) + 1) > num_sheets:
                    num_sheets = max(num_sheets, last_sheet_each)
        if (
            self.abstract
            and (last_sheet_abstract := max(self.abstract.where.pages) + 1) > num_sheets
        ):
            num_sheets = max(num_sheets, last_sheet_abstract)
        if (
            self.reported_counts
            and (
                last_sheet_reported_counts := max(self.reported_counts.where.pages) + 1
            )
            > num_sheets
        ):
            num_sheets = max(num_sheets, last_sheet_reported_counts)
        if self.citations:
            for each in self.citations:
                if (last_sheet_each := max(each.where.pages) + 1) > num_sheets:
                    num_sheets = max(num_sheets, last_sheet_each)

        assert num_sheets >= 0, "FrontMatterData must have at least one page of data"

        object.__setattr__(self, "num_sheets", num_sheets)

    def canonical(self) -> Dict[str, Any]:
        """
        Produce a stable, test-friendly projection of parse_front_page()/parse_front_matter() output.
        v1.1 format - matches bundle_v1_1.FrontMatterV1_1 schema.
        """

        result = {
            "document_type": self.document_type.value,
            "patent_number_normalized": self.patent_id.value if self.patent_id else "",
            "title": self.title.value if self.title else "",
            "assignee": self.assignee.value if self.assignee else "",
            "inventors": [each.value.name for each in self.inventors]
            if self.inventors
            else [],
            "application_number": self.application_number.value
            if self.application_number
            else "",
            "filed_date": self.filed_date.value if self.filed_date else "",
            "grant_date": self.grant_date.value if self.grant_date else "",
            "abstract": self.abstract.value if self.abstract else "",
            "reported_claim_count": self.reported_counts.value.reported_claim_count
            if self.reported_counts
            else 0,
            "reported_drawing_sheet_count": self.reported_counts.value.reported_drawing_sheet_count
            if self.reported_counts
            else 0,
            "cited_us_patents": [
                each.value.canonical
                for each in (self.citations or [])
                if each.value.type == "US_GRANT"
            ],
            "cited_us_publications": [
                each.value.canonical
                for each in (self.citations or [])
                if each.value.type == "US_PUBAPP"
            ],
            "num_sheets": self.num_sheets,
        }

        # Add PCT-specific field if present
        if self.s371_date:
            result["s371_date"] = self.s371_date.value

        return result


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

        print("INID BLOCKS FOUND:", inid_blocks)
        patent_id = extract_patent_id(self.pages, inid_blocks, diagnostics)
        print("PATENT ID FOUND:", patent_id)

        # Detect document type early - affects field extraction
        doc_type_info = detect_document_type(self.pages, inid_blocks, patent_id)
        doc_type = doc_type_info.doc_type
        print(
            f"DOCUMENT TYPE: {doc_type.value} (confidence: {doc_type_info.confidence})"
        )

        title = extract_title(self.pages, inid_blocks, diagnostics)
        print("TITLE FOUND:", title)

        # Extract fields based on document type
        application_number = None
        filed_date = None
        s371_date = None

        if doc_type == DocumentType.PCT_APPLICATION:
            # PCT-specific extractors
            application_number = extract_pct_application_number(
                inid_blocks, diagnostics
            )
            filed_date = extract_pct_filed_date(inid_blocks, diagnostics)
            s371_date = extract_s371_date(inid_blocks, diagnostics)
            print("PCT APP NO FOUND:", application_number)
            print("PCT FILED DATE FOUND:", filed_date)
            print("S371 DATE FOUND:", s371_date)
        else:
            # Standard extractors for granted/published applications
            application_number = extract_application_number(
                self.pages, inid_blocks, diagnostics
            )
            filed_date = extract_filed_date(self.pages, inid_blocks, diagnostics)
            print("APP NO FOUND:", application_number)
            print("FILED DATE FOUND:", filed_date)

        grant_date = extract_grant_date(self.pages, inid_blocks, diagnostics)
        print("GRANT DATE FOUND:", grant_date)

        assignee = extract_assignee(inid_blocks, diagnostics)
        print("ASSIGNEE FOUND:", assignee)
        inventors = extract_inventors(self.pages, inid_blocks, diagnostics)
        print("INVENTORS FOUND:", inventors)
        abstract = extract_abstract(self.pages, diagnostics)
        print("ABSTRACT FOUND:", abstract)

        # PCT applications typically don't have counts in front matter
        reported_counts = None
        if doc_type != DocumentType.PCT_APPLICATION:
            reported_counts = extract_reported_counts(self.pages, diagnostics)
            print("COUNTS FOUND:", reported_counts)
        else:
            print("COUNTS SKIPPED (PCT)")

        citations = extract_citations(self.pages, diagnostics)
        print("CITATIONS FOUND:", citations)

        parsed = FrontMatterData(
            inid_blocks=inid_blocks,
            document_type=doc_type,
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
            s371_date=s371_date,
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
    reported_counts = extract_reported_counts(doc, diag)
    print("REPORTED COUNTS:", reported_counts)

    inferred_drawing_sheet_count = None
    drawing_sheet_start_index = None

    if reported_counts is not None:
        reported_drawing_sheet_count = (
            reported_counts.value.reported_drawing_sheet_count
        )
        result = infer_drawings_start_index(
            doc, reported_drawing_sheet_count=reported_drawing_sheet_count, diag=diag
        )
        if result is not None:
            drawing_sheet_start_index, inferred_drawing_sheet_count = result
        print("DRAWING SHEET START INDEX:", drawing_sheet_start_index)
        if drawing_sheet_start_index is None:
            diag.warn(
                "front_matter.infer_drawings_start_index_failed",
                "Failed to infer drawings start index with reported counts; trying header search.",
                field="document",
            )
            # Fallback to header search without expected count
            result = infer_drawings_start_index_by_sheet_header(
                doc, expected_sheets=None, search_start=1, search_limit=25
            )
            if result is not None:
                drawing_sheet_start_index, inferred_drawing_sheet_count = result
    else:
        print("NO REPORTED COUNTS")
        # Try to infer from sheet headers without knowing expected count
        result = infer_drawings_start_index_by_sheet_header(
            doc, expected_sheets=None, search_start=1, search_limit=25
        )
        if result is not None:
            drawing_sheet_start_index, inferred_drawing_sheet_count = result
        print("DRAWING SHEET START INDEX BY HEADER:", drawing_sheet_start_index)
        print("INFERRED DRAWING SHEET COUNT:", inferred_drawing_sheet_count)

    print("FALLBACK DRAWING SHEET START INDEX:", drawing_sheet_start_index)
    if drawing_sheet_start_index is None:
        # Last resort: assume front matter is just the first page
        diag.error(
            "front_matter.no_drawing_sheet_marker",
            "Could not find drawing sheet markers; assuming front matter is first page only.",
            field="document",
        )
        drawing_sheet_start_index = 1

    front_matter = FrontMatter(doc.subset(pages=range(0, drawing_sheet_start_index)))
    print("MAIN PARSE")
    print("FRONT MATTER:", front_matter.pages.linearize())
    raise Exception("STOP")
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

    meta = {}
    if inferred_drawing_sheet_count is not None:
        meta["inferred_drawing_sheet_count"] = inferred_drawing_sheet_count

    return FrontMatterResult(status=status, data=data, diagnostics=diag, meta=meta)

    # Parse


def infer_drawings_start_index(
    doc: MultiPage, reported_drawing_sheet_count: int, diag: Diagnostics
) -> Optional[Tuple[int, Optional[int]]]:
    """
    Returns:
        Tuple of (start_page_index, inferred_sheet_count) or None if not found
    """
    return infer_drawings_start_index_by_sheet_header(
        doc,
        expected_sheets=reported_drawing_sheet_count,
        search_start=1,
        search_limit=len(doc) - 1,
    )


SHEET_OF_N_PAT = re.compile(
    r"\s*(\d{1,3})\s*\bof\b\s*(\d{1,3})\b",
    re.IGNORECASE,
)


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def infer_drawings_start_index_by_sheet_header(
    doc: MultiPage,
    *,
    expected_sheets: Optional[int] = None,
    search_start: int = 1,
    search_limit: int = 25,
) -> Optional[Tuple[int, Optional[int]]]:
    """
    Prefer explicit 'Sheet i of n' markers to locate the drawings block.
    Assumes drawings sheets are consecutive pages once started.

    Args:
        doc: Document to search
        expected_sheets: Expected number of drawing sheets (if known from counts)
        search_start: Page index to start searching from
        search_limit: Maximum number of pages to search

    Returns:
        Tuple of (start_page_index, inferred_sheet_count) or None if not found
        inferred_sheet_count will be the 'n' from "Sheet 1 of n" if found
    """
    n_pages = len(doc)
    if n_pages <= 1:
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
    if expected_sheets is not None:
        for idx, i, n in sheet_hits:
            if i == 1 and n == expected_sheets:
                return (idx, n)

        # Otherwise choose earliest hit with n == expected_sheets
        for idx, i, n in sheet_hits:
            if n == expected_sheets:
                return (idx, n)

    # If no expected_sheets or no match, prefer earliest "Sheet 1 of N"
    for idx, i, n in sheet_hits:
        if i == 1:
            return (idx, n)  # Return both start index and inferred count

    # Fallback: earliest hit with any sheet marker
    idx, i, n = sheet_hits[0]
    return (idx, n)
