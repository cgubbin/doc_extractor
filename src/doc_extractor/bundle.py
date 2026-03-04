"""Enhanced API for working with patent bundles.

This module provides convenience methods for:
- Loading and querying patent bundles
- Extracting specific figures with context (for external LLM grading tools)
- Analyzing claim dependencies
- Batch operations

Note: This module focuses on data extraction and bundling.
Prompt generation and LLM interaction are handled by external libraries.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Callable

from doc_extractor.load import (
    PatentDocument,
    FigureDescription,
)
from doc_extractor.body.claims import Claim
from doc_extractor.structured_logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class FigureContext:
    """A figure with all its associated context.

    Use this to bundle everything an external LLM grading tool needs:
    - Figure metadata and description
    - Image file paths
    - Claims that reference this figure
    - Text excerpts mentioning the figure
    """

    figure_id: str  # e.g., "3A"
    figure_number: int
    figure_suffix: str
    description: str

    # Image paths (absolute paths to files in bundle)
    sheet_png: str | None  # Path to full sheet containing this figure
    figure_png: str | None  # Path to cropped figure region (if available)

    # Related claims that reference this figure
    related_claims: list[Claim] = field(default_factory=list)

    # Section text that mentions this figure (section_name, excerpt)
    relevant_excerpts: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class ClaimContext:
    """A claim with full dependency context.

    Use this to understand claim relationships:
    - Parent claims (that this claim depends on)
    - Child claims (that depend on this claim)
    - Figures referenced in the claim text
    """

    claim: Claim
    parent_claims: list[Claim] = field(default_factory=list)  # Claims this depends on
    child_claims: list[Claim] = field(
        default_factory=list
    )  # Claims that depend on this
    referenced_figures: list[str] = field(
        default_factory=list
    )  # Figure IDs mentioned in claim text


class EnhancedPatentDocument:
    """Enhanced wrapper around PatentDocument with query and export methods."""

    def __init__(self, doc: PatentDocument):
        self.doc = doc
        self._claims_by_number: dict[int, Claim] = {c.number: c for c in doc.claims}
        self._figures_by_id: dict[str, FigureDescription] = {}

        # Build figure lookup
        for fig in doc.figure_descriptions:
            suffix = fig.suffix if fig.suffix else ""
            fig_id = f"{fig.number}{suffix}".upper()
            self._figures_by_id[fig_id] = fig

    # ==================== Text Content Access ====================

    def get_abstract(self) -> str:
        """Get the patent abstract."""
        return self.doc.meta.abstract

    def get_background(self) -> str:
        """Get the background section text."""
        return self.doc.sections.background

    def get_summary(self) -> str:
        """Get the summary section text."""
        return self.doc.sections.summary

    def get_detailed_description(self) -> str:
        """Get the detailed description section text."""
        return self.doc.sections.detailed_description

    def get_all_text_sections(self) -> dict[str, str]:
        """Get all major text sections in one dict.

        Returns:
            Dict with keys: abstract, background, summary, detailed_description
        """
        return {
            "abstract": self.get_abstract(),
            "background": self.get_background(),
            "summary": self.get_summary(),
            "detailed_description": self.get_detailed_description(),
        }

    # ==================== Query Methods ====================

    def get_claim(self, number: int) -> Claim | None:
        """Get a specific claim by number."""
        return self._claims_by_number.get(number)

    def get_independent_claims(self) -> list[Claim]:
        """Get all independent claims."""
        return [c for c in self.doc.claims if c.is_independent]

    def get_dependent_claims(self) -> list[Claim]:
        """Get all dependent claims."""
        return [c for c in self.doc.claims if not c.is_independent]

    def find_claims_depending_on(self, claim_number: int) -> list[Claim]:
        """Find all claims that directly depend on the given claim."""
        return [c for c in self.doc.claims if claim_number in c.depends_on]

    def get_claim_tree(self, root_claim_number: int) -> dict:
        """Build a dependency tree starting from a root claim.

        Returns:
            Nested dict representing the claim dependency tree
        """
        root = self.get_claim(root_claim_number)
        if not root:
            return {}

        def build_tree(claim: Claim) -> dict:
            children = self.find_claims_depending_on(claim.number)
            return {
                "claim": claim.number,
                "text": claim.text[:100] + "..."
                if len(claim.text) > 100
                else claim.text,
                "is_independent": claim.is_independent,
                "children": [build_tree(child) for child in children],
            }

        return build_tree(root)

    def get_figure(self, figure_id: str) -> FigureDescription | None:
        """Get figure by ID (e.g., '3A', '5')."""
        return self._figures_by_id.get(figure_id.upper())

    def search_text(
        self, query: str, *, case_sensitive: bool = False
    ) -> list[tuple[str, str]]:
        """Search for text across all sections.

        Returns:
            List of (section_name, excerpt) tuples containing the query
        """
        results = []
        query_str = query if case_sensitive else query.lower()

        sections = {
            "abstract": self.doc.meta.abstract,
            "background": self.doc.sections.background,
            "summary": self.doc.sections.summary,
            "detailed_description": self.doc.sections.detailed_description,
        }

        for section_name, text in sections.items():
            search_text = text if case_sensitive else text.lower()
            if query_str in search_text:
                # Find position and extract excerpt
                idx = search_text.find(query_str)
                start = max(0, idx - 100)
                end = min(len(text), idx + len(query) + 100)
                excerpt = text[start:end]
                results.append((section_name, excerpt))

        return results

    # ==================== Citation/Reference Methods ====================

    def get_cited_patents(self) -> list[str]:
        """Get list of cited US patent numbers.

        Returns:
            List of patent numbers (e.g., ["7123456", "8234567"])
        """
        return self.doc.meta.cited_us_patents

    def get_cited_publications(self) -> list[str]:
        """Get list of cited US publication numbers.

        Returns:
            List of publication numbers
        """
        return self.doc.meta.cited_us_publications

    def get_all_citations(self) -> dict[str, list[str]]:
        """Get all citations organized by type.

        Returns:
            Dict with keys: us_patents, us_publications
        """
        return {
            "us_patents": self.get_cited_patents(),
            "us_publications": self.get_cited_publications(),
        }

    # ==================== LLM Grading Context Methods ====================

    def get_figure_context(
        self, figure_id: str, *, include_claims: bool = True
    ) -> FigureContext | None:
        """Get a figure with all relevant context for LLM grading.

        Args:
            figure_id: Figure identifier (e.g., "3A", "5")
            include_claims: Whether to find claims that reference this figure

        Returns:
            FigureContext with description, images, and related claims
        """
        fig = self.get_figure(figure_id)
        if not fig:
            return None

        fig_id_upper = figure_id.upper()

        # Find image paths
        sheet_png = None
        figure_png = None

        # Look for sheet containing this figure (heuristic: sheet_N.png)
        # TODO: This could be improved with explicit sheet->figure mapping from segmentation
        for png_path in self.doc.sheet_pngs:
            if (
                f"sheet_{fig.number}" in png_path.lower()
                or f"sheet{fig.number}" in png_path.lower()
            ):
                sheet_png = str(Path(self.doc.data_dir) / png_path)
                break

        # Look for cropped figure region
        for png_path in self.doc.figure_pngs:
            if fig_id_upper in png_path.upper():
                figure_png = str(Path(self.doc.data_dir) / png_path)
                break

        # Find related claims
        related_claims = []
        if include_claims:
            # Search for "FIG. {id}" or "FIGS. ... {id}" in claim text
            import re

            fig_pattern = re.compile(
                rf"\bFIGS?\.?\s+(?:[0-9A-Z,\s\-]+\s+(?:and\s+)?)?{re.escape(fig_id_upper)}\b",
                re.IGNORECASE,
            )

            for claim in self.doc.claims:
                if fig_pattern.search(claim.text):
                    related_claims.append(claim)

        # Find relevant excerpts mentioning this figure
        excerpts = self.search_text(f"FIG. {fig_id_upper}")

        return FigureContext(
            figure_id=fig_id_upper,
            figure_number=fig.number,
            figure_suffix=fig.suffix,
            description=fig.description,
            sheet_png=sheet_png,
            figure_png=figure_png,
            related_claims=related_claims,
            relevant_excerpts=excerpts,
        )

    def get_claim_context(self, claim_number: int) -> ClaimContext | None:
        """Get a claim with full dependency context for LLM analysis."""
        claim = self.get_claim(claim_number)
        if not claim:
            return None

        # Get parent claims (that this claim depends on)
        parent_claims = [
            self.get_claim(dep_num)
            for dep_num in claim.depends_on
            if self.get_claim(dep_num)
        ]

        # Get child claims (that depend on this claim)
        child_claims = self.find_claims_depending_on(claim_number)

        # Find referenced figures in claim text
        import re

        fig_matches = re.findall(
            r"\bFIGS?\.?\s+([0-9]+[A-Z]?(?:\s*[-,]\s*[0-9]+[A-Z]?)*)",
            claim.text,
            re.IGNORECASE,
        )
        referenced_figures = []
        for match in fig_matches:
            # Parse figure ranges like "3A-3C" or lists like "1, 2, 3"
            figs = re.findall(r"([0-9]+[A-Z]?)", match)
            referenced_figures.extend(figs)

        return ClaimContext(
            claim=claim,
            parent_claims=parent_claims,
            child_claims=child_claims,
            referenced_figures=list(set(referenced_figures)),
        )

    def get_figures_for_grading(
        self, figure_ids: list[str] | None = None, *, include_claims: bool = True
    ) -> list[FigureContext]:
        """Get multiple figures with context for batch LLM grading.

        Args:
            figure_ids: Specific figures to include, or None for all
            include_claims: Whether to include related claims

        Returns:
            List of FigureContext objects ready for LLM prompts
        """
        if figure_ids is None:
            figure_ids = list(self._figures_by_id.keys())

        contexts = []
        for fig_id in figure_ids:
            ctx = self.get_figure_context(fig_id, include_claims=include_claims)
            if ctx:
                contexts.append(ctx)

        return contexts

    # ==================== Export Methods ====================

    def to_json(self) -> dict:
        """Export to JSON-serializable dict."""
        return {
            "meta": {
                "id": self.doc.meta.id,
                "title": self.doc.meta.title,
                "assignee": self.doc.meta.assignee,
                "inventors": self.doc.meta.inventors,
                "application_number": self.doc.meta.application_number,
                "filed_date": self.doc.meta.filed_date,
                "grant_date": self.doc.meta.grant_date,
            },
            "claims": [
                {
                    "number": c.number,
                    "text": c.text,
                    "is_independent": c.is_independent,
                    "depends_on": c.depends_on,
                }
                for c in self.doc.claims
            ],
            "figures": [
                {
                    "id": f"{f.number}{f.suffix}",
                    "number": f.number,
                    "suffix": f.suffix,
                    "description": f.description,
                }
                for f in self.doc.figure_descriptions
            ],
            "sections": {
                "background": self.doc.sections.background,
                "summary": self.doc.sections.summary,
                "detailed_description": self.doc.sections.detailed_description,
            },
        }

    def get_statistics(self) -> dict:
        """Get summary statistics about this patent."""
        return {
            "patent_id": self.doc.meta.id,
            "total_claims": len(self.doc.claims),
            "independent_claims": len(self.get_independent_claims()),
            "dependent_claims": len(self.get_dependent_claims()),
            "total_figures": len(self.doc.figure_descriptions),
            "has_sheet_images": len(self.doc.sheet_pngs) > 0,
            "has_figure_images": len(self.doc.figure_pngs) > 0,
            "inventors_count": len(self.doc.meta.inventors),
            "assignee": self.doc.meta.assignee,
            "grant_date": self.doc.meta.grant_date,
        }


# ==================== Batch Loading Utilities ====================


def load_patent(bundle_dir: str | Path) -> EnhancedPatentDocument:
    """Load a patent bundle with enhanced API.

    Args:
        bundle_dir: Path to bundle directory (e.g., "output/US12345B2")

    Returns:
        EnhancedPatentDocument with query and export methods
    """
    from doc_extractor.load import load_patent as lp

    doc = lp(str(bundle_dir))
    return EnhancedPatentDocument(doc)


def load_patents_from_directory(
    directory: str | Path, *, pattern: str = "*/manifest.json"
) -> Iterator[EnhancedPatentDocument]:
    """Load all patents from a directory.

    Args:
        directory: Parent directory containing patent bundles
        pattern: Glob pattern to find bundles (default: */manifest.json)

    Yields:
        EnhancedPatentDocument for each bundle found
    """
    base_dir = Path(directory)
    for manifest_path in base_dir.glob(pattern):
        bundle_dir = manifest_path.parent
        try:
            yield load_patent(bundle_dir)
        except Exception as e:
            # Log error but continue processing other patents
            logger.warning("failed_to_load_patent", bundle_dir=str(bundle_dir), error=str(e))
            continue


def filter_patents(
    patents: list[EnhancedPatentDocument],
    predicate: Callable[[EnhancedPatentDocument], bool],
) -> list[EnhancedPatentDocument]:
    """Filter patents based on a predicate function.

    Example:
        # Get all patents with more than 20 claims
        many_claims = filter_patents(patents, lambda p: len(p.doc.claims) > 20)

        # Get patents from specific assignee
        microsoft = filter_patents(patents, lambda p: "Microsoft" in p.doc.meta.assignee)
    """
    return [p for p in patents if predicate(p)]


# ==================== Citation Context Tree Utilities ====================


@dataclass(frozen=True)
class CitationContext:
    """Context about a patent's citations for building citation graphs.

    Use this to understand the patent's place in the citation network.
    """

    patent_id: str
    cited_patents: list[str]  # Patents this one cites (backward refs)
    cited_publications: list[str]  # Publications this one cites
    total_citations: int  # Total number of citations

    # For multi-patent analysis (requires loading multiple patents)
    citing_patents: list[str] = field(
        default_factory=list
    )  # Patents that cite this one (forward refs)


def build_citation_context(patent: EnhancedPatentDocument) -> CitationContext:
    """Build citation context for a single patent.

    Args:
        patent: Patent to analyze

    Returns:
        CitationContext with citation information
    """
    cited_patents = patent.get_cited_patents()
    cited_pubs = patent.get_cited_publications()

    return CitationContext(
        patent_id=patent.doc.meta.id,
        cited_patents=cited_patents,
        cited_publications=cited_pubs,
        total_citations=len(cited_patents) + len(cited_pubs),
        citing_patents=[],  # Will be filled by build_citation_graph
    )


def build_citation_graph(
    patents: list[EnhancedPatentDocument],
) -> dict[str, CitationContext]:
    """Build a complete citation graph from multiple patents.

    This analyzes all patents together to find both backward and forward citations.

    Args:
        patents: List of patents to analyze

    Returns:
        Dict mapping patent_id -> CitationContext with forward refs filled in

    Example:
        patents = list(load_patents_from_directory("output"))
        graph = build_citation_graph(patents)

        # Find patents with many citations
        highly_cited = {
            pid: ctx for pid, ctx in graph.items()
            if len(ctx.citing_patents) > 5
        }

        # Find citation chains
        patent = graph["US7629993B2"]
        for cited_id in patent.cited_patents:
            if cited_id in graph:
                print(f"  {cited_id} is also in our corpus")
    """
    # Build initial contexts
    contexts = {p.doc.meta.id: build_citation_context(p) for p in patents}

    # Build reverse index (forward citations)
    citation_index: dict[str, list[str]] = {}
    for patent_id, ctx in contexts.items():
        for cited_id in ctx.cited_patents:
            if cited_id not in citation_index:
                citation_index[cited_id] = []
            citation_index[cited_id].append(patent_id)

    # Update contexts with forward citations
    updated_contexts = {}
    for patent_id, ctx in contexts.items():
        citing = citation_index.get(patent_id, [])
        updated_contexts[patent_id] = CitationContext(
            patent_id=ctx.patent_id,
            cited_patents=ctx.cited_patents,
            cited_publications=ctx.cited_publications,
            total_citations=ctx.total_citations,
            citing_patents=citing,
        )

    return updated_contexts


def find_citation_chain(
    start_patent_id: str,
    end_patent_id: str,
    graph: dict[str, CitationContext],
    max_depth: int = 5,
) -> list[str] | None:
    """Find a citation chain between two patents.

    Args:
        start_patent_id: Starting patent
        end_patent_id: Target patent
        graph: Citation graph from build_citation_graph
        max_depth: Maximum chain length to search

    Returns:
        List of patent IDs forming the chain, or None if no chain exists

    Example:
        chain = find_citation_chain("US7629993B2", "US6123456B1", graph)
        if chain:
            print("Citation chain:", " -> ".join(chain))
    """
    if start_patent_id not in graph:
        return None

    # BFS to find shortest path
    from collections import deque

    queue = deque([(start_patent_id, [start_patent_id])])
    visited = {start_patent_id}

    while queue:
        current_id, path = queue.popleft()

        if len(path) > max_depth:
            continue

        if current_id == end_patent_id:
            return path

        ctx = graph.get(current_id)
        if not ctx:
            continue

        # Follow backward citations
        for cited_id in ctx.cited_patents:
            if cited_id not in visited and cited_id in graph:
                visited.add(cited_id)
                queue.append((cited_id, path + [cited_id]))

    return None
