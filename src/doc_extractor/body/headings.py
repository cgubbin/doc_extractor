# src/doc_extractor/body/headings.py
"""
Re-export shim — section heading rules now live in common/section_rules.py.

All callers that import from this module continue to work unchanged.
"""

from doc_extractor.common.section_rules import (  # noqa: F401
    SectionKey,
    SectionRule,
    normalize_section_heading,
    is_known_section_heading,
    _RULES,
    _COMPILED_RULES,
)
