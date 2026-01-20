# Patent Ingest Refactoring Notes

This document captures structural improvements identified during Phase 1 refactoring (Jan 2026).

## Phase 1 Complete ✅

### Achievements:
- **Removed ~450 lines of duplicated/dead code**
- **Created `common/` module** with 520 lines of organized utilities
- **Updated all parsing modules** to use common utilities and patterns
- **All integration tests passing**

### New Common Module Structure:
```
src/patent_ingest/common/
├── __init__.py          # Clean exports
├── text_utils.py        # 6 text normalization functions
├── span_utils.py        # 3 span manipulation utilities
├── patterns.py          # 20+ shared regex patterns
└── config.py            # SegmentationConfig, ParsingConfig dataclasses
```

---

## Structural Improvements for Future (Phase 4)

### 1. `drawing_sheets/segment.py` - HIGHEST PRIORITY

**Current State:** 1,050 lines in single file

**Issues:**
- `_segment_drawings_on_page()` is 360 lines - does everything
- Mixed abstraction levels (low-level OpenCV + high-level business logic)
- 15+ configuration parameters scattered
- Very difficult to test

**Recommended Structure:**
```python
drawing_sheets/
├── __init__.py                 # Re-export public API
├── model.py                    # Data classes (exists)
├── label_detection.py          # NEW (~200 lines)
│   ├── detect_text_labels()   # PyMuPDF text extraction
│   ├── detect_ocr_labels()    # Tesseract OCR fallback
│   └── parse_figure_label()   # Parse "FIG. 3A" patterns
├── opencv_segmentation.py      # NEW (~250 lines)
│   ├── extract_ink_components()     # Canny + contours
│   ├── merge_nearby_boxes()         # Geometric operations
│   ├── estimate_header_region()     # Header detection
│   └── assign_components_to_labels() # Assignment logic
└── segment.py                  # Main orchestrator (~200 lines)
    ├── segment_sheet()         # Public API
    ├── _apply_fallback_strategies()
    └── _generate_regions()
```

**Benefits:**
- Each module has single responsibility
- OpenCV logic separated from business logic
- Easy to unit test each component
- Reusable components

**Implementation Notes:**
- Extract helper functions first (geometric utils, label parsing)
- Then extract label detection (text + OCR)
- Then extract OpenCV segmentation
- Finally simplify main orchestrator
- Use `SegmentationConfig` from `common/config.py`

---

### 2. `body/parse.py` - MEDIUM PRIORITY

**Current State:** 901 lines in single file

**Issues:**
- `parse_patent_body()` is 160 lines - orchestrates everything
- Mixed concerns: claims, sections, figures all in one file
- Duplicated range expansion logic
- Hard to test individual components

**Recommended Structure:**
```python
body/
├── __init__.py          # Re-export main function
├── model.py             # NEW - Data classes (~100 lines)
│   ├── ClaimsData
│   ├── FiguresData
│   ├── PatentBodyData
│   └── PatentBodyPolicy
├── sections.py          # NEW - Section detection (~150 lines)
│   ├── detect_sections()
│   └── Section heading patterns
├── claims.py            # NEW - Claims extraction (~200 lines)
│   ├── extract_claims_anchor()    # "The invention claimed is"
│   ├── extract_claims_numbered()  # Tail numbered-list heuristic
│   ├── extract_claims_section()   # Section-based fallback
│   └── parse_claims()             # Main with cascade
├── figures.py           # NEW - Figure references (~150 lines)
│   ├── extract_figure_references()
│   ├── parse_drawing_descriptions()
│   └── expand_figure_ranges()
└── parse.py             # Main orchestrator (~100 lines)
    └── parse_patent_body()  # Orchestrates above
```

**Internal Structure of Current File:**
```
Lines 1-100:    Data classes (move to model.py)
Lines 101-480:  Section detection (move to sections.py)
Lines 481-620:  Figure extraction (move to figures.py)
Lines 621-709:  Claims extraction (move to claims.py)
Lines 710-866:  Main orchestrator (stays in parse.py)
Lines 867-901:  Drawing descriptions (move to figures.py)
```

**Benefits:**
- Clear separation of concerns
- Claims strategies become explicit
- Easier to test each component
- Reduced cognitive load

---

### 3. `front_matter/citations.py` - LOW PRIORITY

**Current State:** 790 lines - handles all citation types

**Issues:**
- Large single file
- Multiple citation parsers mixed together

**Recommended Structure:**
```python
front_matter/extractors/
├── citations/
│   ├── __init__.py          # Main extract_citations() function
│   ├── us_grants.py         # US patent number parsing
│   ├── us_publications.py   # US publication parsing
│   └── filtering.py         # Foreign ref filtering, dedup
```

**Note:** Can wait until Phase 4 when writing unit tests. Current structure is acceptable.

---

## Implementation Strategy for Phase 4

When refactoring during test writing:

### For `drawing_sheets/segment.py`:
1. **Start with tests** - Write failing tests for ideal interface
2. **Extract incrementally** - One function at a time
3. **Keep tests passing** - Refactor with green tests
4. **Use `SegmentationConfig`** - Replace 15 parameters with dataclass

### For `body/parse.py`:
1. **Extract data classes first** - Easiest, no logic
2. **Then extract pure functions** - Figure/section detection
3. **Then extract claims logic** - Most complex
4. **Test each step** - Integration tests should stay green

### Testing Strategy:
- **Unit tests** - Test extracted functions in isolation
- **Integration tests** - Keep existing golden tests passing
- **Refactoring** - Extract, test, commit cycle

---

## Key Patterns to Maintain

### Good Patterns (Keep These):
1. **Result pattern** - `status + data + diagnostics + meta`
2. **Frozen dataclasses** - Immutability throughout
3. **Evidence tracking** - Span objects for provenance
4. **Fallback chains** - Primary → fallback → fallback strategies
5. **Diagnostics over exceptions** - Structured errors/warnings

### Anti-patterns to Avoid:
1. **God functions** - Functions doing everything
2. **Mixed abstractions** - Low-level + high-level in same function
3. **Parameter sprawl** - Use dataclasses instead
4. **Implicit configuration** - Make it explicit

---

## Configuration Migration

Already complete:
- ✅ `SegmentationConfig` in `common/config.py`
- ✅ `ParsingConfig` in `common/config.py`

TODO in Phase 4:
- Update `_segment_drawings_on_page()` to accept `SegmentationConfig`
- Update callers to pass config object
- Remove individual parameter passing

---

## Metrics

### Before Phase 1:
- Duplicated functions: 8 instances across 6 files
- Common utilities: Scattered in 4 locations
- Regex patterns: Duplicated in 3 files
- Lines of duplicated code: ~450

### After Phase 1:
- Duplicated functions: 0
- Common utilities: Centralized in `common/`
- Regex patterns: Single source in `patterns.py`
- Lines saved: ~450
- Lines of organized common code: 520

### Future (After Phase 4):
- Target: 80%+ test coverage
- Large files (>500 lines): 0
- Average file size: <200 lines
- Testability: All components independently testable

---

## Dependencies for Refactoring

### Module Dependencies:
```
front_matter/  → common/
body/          → common/
drawing_sheets → common/
pipeline       → front_matter, body, drawing_sheets
api            → pipeline
__main__       → api
```

### Internal Dependencies (drawing_sheets):
```
label_detection.py  → patterns (from common)
opencv_segmentation → label_detection
segment.py          → label_detection, opencv_segmentation, model
```

### Internal Dependencies (body):
```
model.py     → (standalone)
sections.py  → patterns (from common)
claims.py    → patterns (from common)
figures.py   → patterns (from common)
parse.py     → model, sections, claims, figures
```

---

## Quick Wins for Phase 4

1. **Extract data classes** - Easy, no logic, immediate organization benefit
2. **Extract pure functions** - Functions with no side effects
3. **Extract pattern matching** - Regex-heavy functions
4. **Leave orchestrators last** - Main functions that tie everything together

---

## Testing Priorities

### Unit Tests (Phase 4):
1. **Text normalization** - Already in `common/text_utils.py`
2. **Figure label parsing** - Regex matching, ID extraction
3. **Claims strategies** - Each strategy independently
4. **Section detection** - Heading patterns
5. **Geometric functions** - Bounding box operations

### Integration Tests (Phase 5):
1. **Drawing sheets** - Use existing golden file `US9587932B2.drawings.json`
2. **Body parsing** - Create new golden files
3. **End-to-end** - Full pipeline tests

---

## Questions to Consider During Refactoring

1. **Should label detection be synchronous or async?** (Multiple OCR calls)
2. **Should OpenCV be an optional dependency?** (Currently required)
3. **Should we cache rendered pages?** (Performance vs memory)
4. **Should figure assignment use a scoring model?** (Current: distance + penalties)

---

## References

- Current plan: `/Users/kit/.claude/plans/magical-sprouting-gosling.md`
- Common module: `src/patent_ingest/common/`
- Integration tests: `tests/integration/`
- Golden files: `corpus/gold/`
