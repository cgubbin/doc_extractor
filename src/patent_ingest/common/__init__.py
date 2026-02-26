"""Common utilities shared across patent_ingest modules.

This package contains consolidated utility functions, patterns, and configurations
that were previously duplicated across multiple modules.
"""

# Re-export commonly used utilities for convenience
from patent_ingest.common.text_utils import (
    normalize_whitespace,
    normalize_whitespace_basic,
    normalize_punctuation_spacing,
    normalize_text_field,
    dehyphenate,
    strip_front_page_noise,
    cut_at_heading,
)


from patent_ingest.common.config import (
    SegmentationConfig,
    ParsingConfig,
    DEFAULT_SEGMENTATION_CONFIG,
    DEFAULT_PARSING_CONFIG,
)

# patterns module should be imported as: from patent_ingest.common import patterns

__all__ = [
    # text_utils
    "normalize_whitespace",
    "normalize_whitespace_basic",
    "normalize_punctuation_spacing",
    "normalize_text_field",
    "dehyphenate",
    "strip_front_page_noise",
    "cut_at_heading",
    # config
    "SegmentationConfig",
    "ParsingConfig",
    "DEFAULT_SEGMENTATION_CONFIG",
    "DEFAULT_PARSING_CONFIG",
]
