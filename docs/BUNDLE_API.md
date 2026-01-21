# Patent Bundle API

The `patent_ingest.bundle` module provides a high-level API for working with parsed patent bundles. It's designed to make it easy to extract data for external LLM grading and analysis tools.

## Complete Workflow: PDF to Analysis

### Step 1: Parse PDF and Export Artifacts

First, parse a patent PDF and export artifacts to disk:

```python
from patent_ingest.api import (
    parse_patent,
    export_artifacts,
    ParseOptions,
    ExportSpec,
    FileSystemSink,
)

# Parse the PDF
parse_result = parse_patent(
    pdf_path="data/US7629993B2.pdf",
    doc_id="US7629993B2",
    options=ParseOptions(
        detect_figures=True,
        export_figures_png=True,
        export_sheet_png=True,
    ),
)

# Export artifacts to disk
manifest = export_artifacts(
    pdf_path="data/US7629993B2.pdf",
    parse_result=parse_result,
    sink=FileSystemSink("output/US7629993B2"),
    spec=ExportSpec(
        export_canonical_front_json=True,
        export_body_text=True,
        export_sheet_pdfs=True,
        export_sheet_pngs=True,
        export_figure_pngs=True,
    ),
    doc_id="US7629993B2",
)

# Output directory structure:
# output/US7629993B2/
#   ├── manifest.json
#   ├── front/
#   │   └── metadata.json
#   ├── body/
#   │   ├── sections.json
#   │   ├── claims.json
#   │   └── figures.json
#   └── drawings/
#       ├── sheets/
#       │   ├── sheet_001.png
#       │   └── ...
#       └── regions_png/
#           ├── fig_1.png
#           └── ...
```

### Step 2: Load Patent Bundle

Load the parsed bundle using the high-level API:

```python
from patent_ingest.bundle import load_patent

# Load the patent bundle
patent = load_patent("output/US7629993B2")

# Access metadata
print(f"Patent: {patent.doc.meta.id}")
print(f"Title: {patent.doc.meta.title}")
print(f"Assignee: {patent.doc.meta.assignee}")
print(f"Claims: {len(patent.doc.claims)}")
print(f"Figures: {len(patent.doc.figure_descriptions)}")
```

### Step 3: Extract Data for LLM Grading

Use the bundle API to extract structured data for your external LLM tool:

```python
# Get text sections for context
abstract = patent.get_abstract()
summary = patent.get_summary()
detailed_desc = patent.get_detailed_description()

# Get figures with all context
figures = patent.get_figures_for_grading(include_claims=True)

# Pass to your external LLM grading tool
for fig_ctx in figures:
    your_llm_tool.grade_figure(
        image_path=fig_ctx.figure_png,
        description=fig_ctx.description,
        claims=[c.text for c in fig_ctx.related_claims],
        abstract=abstract,
        summary=summary,
    )
```

### Step 4: Build Citation Context

For multi-patent analysis, build citation graphs:

```python
from patent_ingest.bundle import (
    load_patents_from_directory,
    build_citation_graph,
    find_citation_chain,
)

# Load all patents
patents = list(load_patents_from_directory("output"))

# Build citation graph (forward and backward references)
graph = build_citation_graph(patents)

# Find citation chains between patents
chain = find_citation_chain("US7629993B2", "US10935501B2", graph)
if chain:
    print(f"Citation chain: {' -> '.join(chain)}")
```

## Key Concepts

### Data Containers

- **`FigureContext`**: A figure with all related context (image paths, claims, text excerpts)
- **`ClaimContext`**: A claim with dependency information (parent/child claims, referenced figures)
- **`CitationContext`**: Citation relationships (backward and forward references)
- **`EnhancedPatentDocument`**: Wrapper around `PatentDocument` with convenient query methods

### Design Philosophy

This API focuses on **data extraction only**. It provides:
- ✅ Structured data with all metadata
- ✅ Convenient query methods
- ✅ Context bundling (figure + claims + text)

It does **NOT** provide:
- ❌ Prompt generation (handled by external tools)
- ❌ LLM API calls (handled by external tools)
- ❌ Image encoding (handled by external tools)

## Quick Start

```python
from patent_ingest.bundle import load_patent

# Load a patent bundle
patent = load_patent("output/US7629993B2")

# Get metadata
print(patent.doc.meta.title)
print(patent.doc.meta.assignee)

# Query claims
independent_claims = patent.get_independent_claims()
claim_ctx = patent.get_claim_context(1)

# Get figures with context for LLM grading
fig_ctx = patent.get_figure_context("3A", include_claims=True)
print(f"Figure 3A: {fig_ctx.description}")
print(f"Image path: {fig_ctx.figure_png}")
print(f"Related claims: {len(fig_ctx.related_claims)}")
```

## Common Use Cases

### 1. Extract All Figures for Batch LLM Grading

```python
# Get all figures with their context
all_figures = patent.get_figures_for_grading(include_claims=True)

for fig_ctx in all_figures:
    # Pass to your external LLM grading tool:
    # - fig_ctx.figure_png (image file path)
    # - fig_ctx.description (text description)
    # - fig_ctx.related_claims (list of Claim objects)
    # - fig_ctx.relevant_excerpts (text mentions)

    your_llm_tool.grade_figure(
        image_path=fig_ctx.figure_png,
        description=fig_ctx.description,
        claims=[c.text for c in fig_ctx.related_claims]
    )
```

### 2. Analyze Claim Dependencies

```python
# Get independent claims (most important)
independent = patent.get_independent_claims()

for claim in independent:
    # Get full context
    ctx = patent.get_claim_context(claim.number)

    print(f"Claim {claim.number}:")
    print(f"  Depends on: {[c.number for c in ctx.parent_claims]}")
    print(f"  Has children: {[c.number for c in ctx.child_claims]}")
    print(f"  References figures: {ctx.referenced_figures}")

    # Get dependency tree
    tree = patent.get_claim_tree(claim.number)
```

### 3. Search Patent Text

```python
# Find all sections mentioning "FIG. 3"
results = patent.search_text("FIG. 3")

for section_name, excerpt in results:
    print(f"{section_name}: ...{excerpt}...")
```

### 4. Batch Load Patents

```python
from patent_ingest.bundle import load_patents_from_directory

# Load all patents in a directory
all_patents = list(load_patents_from_directory("output"))

# Filter by criteria
complex_patents = [
    p for p in all_patents
    if len(p.doc.claims) > 20
]

recent_patents = [
    p for p in all_patents
    if p.doc.meta.grant_date >= "2020-01-01"
]
```

### 5. Extract Text Sections for LLM Context

```python
# Get individual text sections
abstract = patent.get_abstract()
background = patent.get_background()
summary = patent.get_summary()
detailed_desc = patent.get_detailed_description()

# Or get all sections at once
all_sections = patent.get_all_text_sections()
# Returns: {
#   'abstract': '...',
#   'background': '...',
#   'summary': '...',
#   'detailed_description': '...'
# }

# Use for LLM prompts
your_llm_tool.analyze_patent(
    abstract=abstract,
    detailed_description=detailed_desc,
    claims=patent.doc.claims,
)
```

### 6. Build Citation Context Trees

```python
from patent_ingest.bundle import (
    load_patents_from_directory,
    build_citation_graph,
    find_citation_chain,
)

# Load all patents in corpus
patents = list(load_patents_from_directory("output"))

# Build complete citation graph
graph = build_citation_graph(patents)

# For each patent, see what it cites and what cites it
for patent_id, ctx in graph.items():
    print(f"{patent_id}:")
    print(f"  Cites {len(ctx.cited_patents)} patents")
    print(f"  Cited by {len(ctx.citing_patents)} patents")

    # Get patents that cite this one (forward references)
    for citing_id in ctx.citing_patents:
        print(f"    ← Cited by {citing_id}")

# Find citation chains between patents
chain = find_citation_chain("US7629993B2", "US10935501B2", graph)
if chain:
    print(f"Citation path: {' -> '.join(chain)}")
```

### 7. Export Structured Data

```python
# Get complete patent data as JSON
data = patent.to_json()

# data contains:
# - meta: {id, title, assignee, inventors, dates, abstract, citations, ...}
# - claims: [{number, text, is_independent, depends_on}, ...]
# - figures: [{id, number, suffix, description}, ...]
# - sections: {background, summary, detailed_description}

# Pass to your external tool
your_tool.process_patent(data)
```

## API Reference

### Loading

```python
load_patent(bundle_dir: str | Path) -> EnhancedPatentDocument
    """Load a single patent bundle."""

load_patents_from_directory(directory: str | Path) -> Iterator[EnhancedPatentDocument]
    """Load all patents from a directory."""
```

### Query Methods

#### Claims

```python
patent.get_claim(number: int) -> Claim | None
    """Get a specific claim by number."""

patent.get_independent_claims() -> list[Claim]
    """Get all independent claims."""

patent.get_dependent_claims() -> list[Claim]
    """Get all dependent claims."""

patent.find_claims_depending_on(claim_number: int) -> list[Claim]
    """Find all claims that depend on the given claim."""

patent.get_claim_tree(root_claim_number: int) -> dict
    """Build a dependency tree starting from a root claim."""
```

#### Figures

```python
patent.get_figure(figure_id: str) -> FigureDescription | None
    """Get figure by ID (e.g., '3A', '5')."""
```

#### Text Sections

```python
patent.get_abstract() -> str
    """Get the patent abstract."""

patent.get_background() -> str
    """Get the background section."""

patent.get_summary() -> str
    """Get the summary section."""

patent.get_detailed_description() -> str
    """Get the detailed description section."""

patent.get_all_text_sections() -> dict[str, str]
    """Get all text sections as a dict.
    Returns: {
        'abstract': '...',
        'background': '...',
        'summary': '...',
        'detailed_description': '...'
    }
    """
```

#### Citations

```python
patent.get_cited_patents() -> list[str]
    """Get list of cited US patent numbers."""

patent.get_cited_publications() -> list[str]
    """Get list of cited US patent publications."""

patent.get_all_citations() -> dict[str, list[str]]
    """Get all citations as a dict.
    Returns: {
        'cited_patents': [...],
        'cited_publications': [...]
    }
    """
```

#### Search

```python
patent.search_text(query: str, case_sensitive: bool = False) -> list[tuple[str, str]]
    """Search for text across all sections. Returns (section_name, excerpt) tuples."""
```

### Context Extraction (for LLM Grading)

```python
patent.get_figure_context(figure_id: str, include_claims: bool = True) -> FigureContext | None
    """Get a figure with all relevant context."""

patent.get_claim_context(claim_number: int) -> ClaimContext | None
    """Get a claim with full dependency context."""

patent.get_figures_for_grading(figure_ids: list[str] | None = None) -> list[FigureContext]
    """Get multiple figures with context for batch LLM grading."""
```

### Export Methods

```python
patent.to_json() -> dict
    """Export to JSON-serializable dict."""

patent.get_statistics() -> dict
    """Get summary statistics about this patent."""
```

### Citation Graph Utilities

These functions work across multiple patents to build citation networks:

```python
build_citation_context(patent: EnhancedPatentDocument) -> CitationContext
    """Build citation context for a single patent.

    Returns CitationContext with:
    - cited_patents: Patents this one cites (backward refs)
    - cited_publications: Publications this one cites
    - total_citations: Total citation count
    - citing_patents: Empty list (need full corpus for forward refs)
    """

build_citation_graph(patents: list[EnhancedPatentDocument]) -> dict[str, CitationContext]
    """Build complete citation graph with forward and backward references.

    Analyzes all patents to determine:
    - What each patent cites (backward references)
    - What cites each patent (forward references)

    Returns dict mapping patent_id -> CitationContext with populated citing_patents.
    """

find_citation_chain(
    start_id: str,
    end_id: str,
    graph: dict[str, CitationContext],
    max_depth: int = 5
) -> list[str] | None
    """Find citation chain from start patent to end patent using BFS.

    Args:
        start_id: Starting patent ID
        end_id: Target patent ID
        graph: Citation graph from build_citation_graph()
        max_depth: Maximum chain length to search

    Returns:
        List of patent IDs forming the chain, or None if no chain found.
        Example: ['US7629993B2', 'US9587932B2', 'US10935501B2']
    """
```

## Data Structures

### FigureContext

```python
@dataclass(frozen=True)
class FigureContext:
    figure_id: str              # e.g., "3A"
    figure_number: int          # e.g., 3
    figure_suffix: str          # e.g., "A"
    description: str            # Full description text

    # Image paths (absolute paths resolved from manifest)
    sheet_png: str | None       # Full sheet image (absolute path)
    figure_png: str | None      # Cropped figure region (absolute path)

    # Related content
    related_claims: list[Claim]                    # Claims referencing this figure
    relevant_excerpts: list[tuple[str, str]]       # (section_name, excerpt)
```

### ClaimContext

```python
@dataclass(frozen=True)
class ClaimContext:
    claim: Claim                      # The claim itself
    parent_claims: list[Claim]        # Claims this depends on
    child_claims: list[Claim]         # Claims that depend on this
    referenced_figures: list[str]     # Figure IDs mentioned in text
```

### CitationContext

```python
@dataclass(frozen=True)
class CitationContext:
    patent_id: str                         # This patent's ID
    cited_patents: list[str]               # US patents cited by this patent (backward refs)
    cited_publications: list[str]          # US publications cited by this patent
    total_citations: int                   # Total number of citations
    citing_patents: list[str]              # Patents that cite this one (forward refs)

# Use build_citation_graph() to get forward references populated
# Use find_citation_chain() to trace citation paths between patents
```

### Claim

```python
@dataclass(frozen=True)
class Claim:
    number: int                  # Claim number
    text: str                    # Full claim text
    depends_on: list[int]        # Parent claim numbers
    is_independent: bool         # True if independent claim
```

## Integration with External LLM Tools

This API is designed to work with external LLM grading tools. Typical workflow:

```python
# 1. Load patent
patent = load_patent("output/US7629993B2")

# 2. Extract text sections for context
abstract = patent.get_abstract()
summary = patent.get_summary()
detailed_desc = patent.get_detailed_description()

# 3. Extract figures with context
figures = patent.get_figures_for_grading()

# 4. For each figure, pass to your external LLM tool
for fig_ctx in figures:
    # Your tool handles:
    # - Loading the image from fig_ctx.figure_png
    # - Creating prompts with fig_ctx.description
    # - Including fig_ctx.related_claims for context
    # - Adding patent text sections (abstract, summary, etc.)
    # - Calling the LLM API
    # - Processing responses

    result = your_llm_grading_tool.grade_figure(
        image_path=fig_ctx.figure_png,
        description=fig_ctx.description,
        related_claims=fig_ctx.related_claims,
        abstract=abstract,
        summary=summary,
        detailed_description=detailed_desc,
        patent_metadata=patent.doc.meta,
    )

    # Process result
    store_grading_result(patent.doc.meta.id, fig_ctx.figure_id, result)
```

### Multi-Patent Analysis with Citation Context

```python
from patent_ingest.bundle import (
    load_patents_from_directory,
    build_citation_graph,
    find_citation_chain,
)

# Load all patents
patents = list(load_patents_from_directory("output"))

# Build citation graph
graph = build_citation_graph(patents)

# Analyze citation relationships
for patent_id, ctx in graph.items():
    patent = next(p for p in patents if p.doc.meta.id == patent_id)

    # Get patents that this one cites
    cited_context = []
    for cited_id in ctx.cited_patents:
        if cited_id in graph:
            cited_patent = next(p for p in patents if p.doc.meta.id == cited_id)
            cited_context.append({
                'id': cited_id,
                'title': cited_patent.doc.meta.title,
                'abstract': cited_patent.get_abstract(),
            })

    # Pass to LLM for analysis
    your_llm_tool.analyze_patent_with_citations(
        patent=patent,
        cited_patents=cited_context,
        citing_patents=ctx.citing_patents,
    )
```

## Examples

See `examples/bundle_api_usage.py` for complete working examples.

## Notes

- The manifest stores image paths as relative paths (e.g., "drawings/regions_png/fig_1.png")
- The bundle API resolves these to absolute paths in FigureContext objects for easy loading
- Figure IDs are case-insensitive (both "3A" and "3a" work)
- Claim dependency trees are built recursively
- Text search returns excerpts with 100 characters of context on each side
- The API gracefully handles missing data (returns None or empty lists)
- Text sections return empty strings if not present in the patent
- Citation graph building requires a corpus of patents; single patent analysis only includes backward references
- Citation chain finding uses BFS with configurable max depth to prevent infinite loops
