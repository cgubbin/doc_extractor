from dataclasses import dataclass
from typing import Dict, List

from patent_ingest.model.document import MultiPage
from patent_ingest.model.span import Column
from patent_ingest.model.mapping import linearize
from patent_ingest.front_matter.abstract import extract_abstract
from patent_ingest.front_matter.citations import extract_citations, CitationId
from patent_ingest.front_matter.counts import extract_reported_counts, ReportedCounts
from patent_ingest.front_matter.assignee import extract_assignee
from patent_ingest.front_matter.inid import parse_inid_blocks_raw, ParsedINIDBlocks
from patent_ingest.front_matter.inventor import extract_inventors
from patent_ingest.front_matter.grant_date import extract_grant_date, extract_filed_date
from patent_ingest.front_matter.application_number import extract_application_number
from patent_ingest.front_matter.patent_id import extract_patent_id
from patent_ingest.front_matter.title import extract_title
from patent_ingest.parsed import ParsedRaw, ParsedNorm, INIDKind, kind_display
from patent_ingest.patent_id import USPatentId
from typing import Any

import logging


@dataclass(frozen=True)
class ParsedFrontMatter:
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
    qa_warnings: List[str] | None = None

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
        }


class FrontMatter(MultiPage):
    inid_blocks: ParsedINIDBlocks

    def __init__(self, document, pages):
        super().__init__(document, pages)

    def parse(
        self,
        sep: str = "\n",
        order: tuple[Column, Column] = (Column.LEFT, Column.RIGHT),
    ) -> ParsedFrontMatter:
        linear_text, segments = linearize(self, sep=sep, order=order)

        # try with the inid blocks
        inid_blocks = parse_inid_blocks_raw(self)

        logger = logging.getLogger(__name__)

        for each, val in inid_blocks.items():
            logger.info(
                f"Found INID block: {kind_display(each)} at {val.where} ({val.text})"
            )

        qa_warnings: List[str] = []

        # First pass through the INID fields to extract
        # patent_id = None
        # if id_block := get_patent_id_raw(self, inid_blocks):
        #     id_block.retag(EntityKind.PATENT_ID, rule="inid_or_header")
        #     patent_id = normalize_us_patent_id(id_block)
        #     if not patent_id:
        #         qa_warnings.append("patent_number_digits_not_found")
        #     print("ID: ", patent_id)
        # else:
        # qa_warnings.append("missing_patent_header_number")

        patent_id = extract_patent_id(self, inid_blocks)
        # print("ID:", patent_id or "")
        if not patent_id:
            qa_warnings.append("missing_patent_id")

        title = extract_title(self, inid_blocks)
        # print("Title", title or "")
        if not title:
            qa_warnings.append("missing_title")

        application_number = extract_application_number(self, inid_blocks)
        # print("Application number: ", application_number or "")
        if not application_number:
            qa_warnings.append("missing_application_number")

        grant_date = extract_grant_date(self, inid_blocks)
        # print("Grant date: ", grant_date or "")
        if not grant_date:
            qa_warnings.append("missing_grant_date")

        filed_date = extract_filed_date(self, inid_blocks)
        # print("Filed date: ", filed_date or "")
        if not filed_date:
            qa_warnings.append("missing_filed_date")

        assignee = extract_assignee(inid_blocks)
        # print("Assignee: ", assignee or "")
        if not assignee:
            qa_warnings.append("missing_assignee")

        inventors = extract_inventors(self, inid_blocks)
        # print("inventors: ", inventors or "")
        if not inventors:
            qa_warnings.append("missing_inventors")

        abstract = extract_abstract(self)
        # print("abstract: ", abstract or "")
        if not abstract:
            qa_warnings.append("missing_abstract")

        reported_counts = extract_reported_counts(self)
        # print("counts: ", reported_counts or "")
        if not abstract:
            qa_warnings.append("missing_counts")

        citations = extract_citations(self)
        # print("citations: ", citations or "")
        if not citations:
            qa_warnings.append("missing_citations")

        # print(len(citations))

        return ParsedFrontMatter(
            inid_blocks=inid_blocks,
            patent_id=patent_id,
            title=title,
            application_number=application_number,
            grant_date=grant_date,
            filed_date=filed_date,
            qa_warnings=qa_warnings,
            assignee=assignee,
            inventors=inventors,
            abstract=abstract,
            reported_counts=reported_counts,
            citations=citations,
        )

        # header = self.parse_header()
        # if header is None:
        # qa_warnings.append("missing_patent_header_number")

        # print(header, header.object.kind_code())
