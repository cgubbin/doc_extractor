#!/usr/bin/env python3
"""
Example: Using the bundle API to extract patent data for external LLM grading tools.

This example shows how to:
1. Load a patent bundle
2. Extract figures with all context (image paths, claims, descriptions)
3. Query claims and their dependencies
4. Export structured data for external processing
"""

from patent_ingest.bundle import load_patent, load_patents_from_directory

# ==================== Basic Loading ====================

def example_load_patent():
    """Load a single patent bundle."""
    patent = load_patent("output/US7629993B2")

    print(f"Patent ID: {patent.doc.meta.id}")
    print(f"Title: {patent.doc.meta.title}")
    print(f"Assignee: {patent.doc.meta.assignee}")
    print(f"Total claims: {len(patent.doc.claims)}")
    print(f"Total figures: {len(patent.doc.figure_descriptions)}")
    print()

    return patent


# ==================== Figure Context Extraction ====================

def example_get_figure_with_context(patent):
    """Get a figure with all related data for LLM grading."""

    # Get Figure 3A with its context
    fig_ctx = patent.get_figure_context("3A", include_claims=True)

    if fig_ctx:
        print("Figure 3A Context:")
        print(f"  ID: {fig_ctx.figure_id}")
        print(f"  Description: {fig_ctx.description[:100]}...")
        print(f"  Cropped image: {fig_ctx.figure_png}")
        print(f"  Sheet image: {fig_ctx.sheet_png}")
        print(f"  Related claims: {len(fig_ctx.related_claims)}")

        # Show which claims reference this figure
        for claim in fig_ctx.related_claims[:2]:  # First 2 claims
            print(f"\n  Claim {claim.number} ({claim.text[:80]}...)")

        # Your external LLM tool would:
        # 1. Read the image file from fig_ctx.figure_png or fig_ctx.sheet_png
        # 2. Pass the image + fig_ctx.description + fig_ctx.related_claims
        # 3. Generate prompts and call LLM externally


# ==================== Batch Figure Extraction ====================

def example_get_all_figures_for_grading(patent):
    """Get all figures ready for batch LLM grading."""

    all_figures = patent.get_figures_for_grading(include_claims=True)

    print(f"\nExtracted {len(all_figures)} figures for grading:")

    for fig_ctx in all_figures:
        has_image = fig_ctx.figure_png or fig_ctx.sheet_png
        print(f"  Figure {fig_ctx.figure_id}: "
              f"has_image={has_image}, "
              f"related_claims={len(fig_ctx.related_claims)}")

    # Your grading pipeline would iterate through all_figures
    # and process each one with your LLM
    return all_figures


# ==================== Claim Analysis ====================

def example_analyze_claims(patent):
    """Analyze claim structure and dependencies."""

    # Get independent claims (most important)
    independent = patent.get_independent_claims()
    print(f"\nIndependent claims: {[c.number for c in independent]}")

    # Get claim with full context
    claim_ctx = patent.get_claim_context(1)  # Claim 1

    if claim_ctx:
        print(f"\nClaim 1 context:")
        print(f"  Text: {claim_ctx.claim.text[:100]}...")
        print(f"  Is independent: {claim_ctx.claim.is_independent}")
        print(f"  Depends on: {claim_ctx.claim.depends_on}")
        print(f"  Child claims: {[c.number for c in claim_ctx.child_claims]}")
        print(f"  References figures: {claim_ctx.referenced_figures}")

    # Get dependency tree
    tree = patent.get_claim_tree(1)
    print(f"\nClaim 1 dependency tree: {tree}")


# ==================== Search and Query ====================

def example_search_patent(patent):
    """Search for specific content in patent text."""

    # Search for mentions of "FIG. 3"
    results = patent.search_text("FIG. 3", case_sensitive=False)

    print(f"\nFound 'FIG. 3' in {len(results)} sections:")
    for section_name, excerpt in results:
        print(f"  {section_name}: ...{excerpt[:80]}...")


# ==================== Data Export ====================

def example_export_structured_data(patent):
    """Export patent data as structured JSON."""

    # Get complete structured data
    data = patent.to_json()

    print(f"\nStructured data export:")
    print(f"  Meta: {list(data['meta'].keys())}")
    print(f"  Claims: {len(data['claims'])} items")
    print(f"  Figures: {len(data['figures'])} items")
    print(f"  Sections: {list(data['sections'].keys())}")

    # Your external tool can consume this JSON directly
    return data


# ==================== Statistics ====================

def example_get_statistics(patent):
    """Get patent statistics."""

    stats = patent.get_statistics()

    print(f"\nPatent Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


# ==================== Batch Loading ====================

def example_batch_load():
    """Load multiple patents from a directory."""

    # Load all patents in output/ directory
    patents = list(load_patents_from_directory("output"))

    print(f"\nLoaded {len(patents)} patents")

    # Filter patents with many claims
    complex_patents = [p for p in patents if len(p.doc.claims) > 15]
    print(f"Found {len(complex_patents)} patents with >15 claims")

    # Filter by assignee
    microsoft_patents = [
        p for p in patents
        if "Microsoft" in p.doc.meta.assignee
    ]
    print(f"Found {len(microsoft_patents)} Microsoft patents")


if __name__ == "__main__":
    print("=" * 70)
    print("Patent Bundle API Usage Examples")
    print("=" * 70)

    # Load a patent
    patent = example_load_patent()

    # Extract figures with context
    example_get_figure_with_context(patent)

    # Get all figures for batch grading
    figures = example_get_all_figures_for_grading(patent)

    # Analyze claims
    example_analyze_claims(patent)

    # Search patent text
    example_search_patent(patent)

    # Export structured data
    data = example_export_structured_data(patent)

    # Get statistics
    example_get_statistics(patent)

    print("\n" + "=" * 70)
    print("These data structures are ready to be passed to your")
    print("external LLM grading tool, which will handle:")
    print("  - Prompt generation")
    print("  - Image loading and encoding")
    print("  - LLM API calls")
    print("  - Response processing")
    print("=" * 70)
