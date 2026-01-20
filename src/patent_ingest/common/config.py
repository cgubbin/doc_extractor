"""Configuration dataclasses for patent parsing.

This module contains configuration classes that consolidate the various
parameters used across different parsing modules, particularly for drawing
sheet segmentation which previously had 15+ scattered parameters.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class SegmentationConfig:
    """Configuration for drawing sheet figure segmentation.

    This consolidates the numerous OpenCV and figure detection parameters
    that were previously passed as individual function arguments.

    Attributes:
        # Figure detection
        detect_figures: Whether to detect figure labels on sheets
        figure_text_first: Try text extraction before OCR
        figure_ocr_fallback: Fall back to OCR if text extraction fails
        figure_ocr_dpi: DPI for OCR rendering

        # Rendering
        png_dpi: DPI for page rendering during segmentation

        # OpenCV segmentation
        use_opencv: Whether to use OpenCV-based segmentation
        opencv_canny1: Canny edge detection lower threshold
        opencv_canny2: Canny edge detection upper threshold
        opencv_dilate_iter: Number of dilation iterations
        opencv_min_area_px: Minimum component area in pixels
        opencv_merge_gap_px: Gap distance for merging nearby components
        opencv_crop_margin_px: Margin to add around detected components

        # Component-to-label assignment
        label_exclusion_pad_px: Padding around labels to exclude components
        assign_prefer_above_label: Prefer components above label position
        assign_below_penalty: Distance penalty for components below labels
        assign_label_overlap_penalty: Penalty for components overlapping labels
        min_crop_area_frac: Minimum crop area as fraction of page
        fallback_radius_frac: Radius fraction for fallback search
    """

    # Figure detection
    detect_figures: bool = True
    figure_text_first: bool = True
    figure_ocr_fallback: bool = True
    figure_ocr_dpi: int = 200

    # Rendering DPI
    png_dpi: int = 200

    # OpenCV segmentation
    use_opencv: bool = True
    opencv_canny1: int = 50
    opencv_canny2: int = 150
    opencv_dilate_iter: int = 2
    opencv_min_area_px: int = 900
    opencv_merge_gap_px: int = 12
    opencv_crop_margin_px: int = 12

    # Component assignment
    label_exclusion_pad_px: int = 12
    assign_prefer_above_label: bool = True
    assign_below_penalty: float = 3.0
    assign_label_overlap_penalty: float = 5.0
    min_crop_area_frac: float = 0.02
    fallback_radius_frac: float = 0.60


@dataclass(frozen=True)
class ParsingConfig:
    """General configuration for patent parsing.

    Attributes:
        confidence_threshold: Minimum confidence for accepting parsed values
        max_pages_front_matter: Maximum pages to scan for front matter
        max_pages_drawings: Maximum pages to process as drawing sheets
        strict_validation: Whether to fail on validation warnings
    """

    confidence_threshold: float = 0.3
    max_pages_front_matter: int = 10
    max_pages_drawings: int = 50
    strict_validation: bool = False


# Default configurations
DEFAULT_SEGMENTATION_CONFIG = SegmentationConfig()
DEFAULT_PARSING_CONFIG = ParsingConfig()
