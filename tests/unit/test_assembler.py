from __future__ import annotations

from patent_ingest.assembler import assemble_parsed_patent


def _base_front(expected_claims: int | None = 16, expected_sheets: int | None = 4) -> dict:
    return {
        "reported_counts": {
            "reported_claim_count": expected_claims,
            "reported_drawing_sheet_count": expected_sheets,
        },
        "qa": {"warnings": [], "info": {}},
    }


def _base_drawings(figures_flat: list[dict]) -> dict:
    return {
        "figures": figures_flat,
        "qa": {"warnings": [], "info": {}},
        "drawing_sheets": {"sheet_count": 4},
    }


def _base_body(
    claims_count: int = 16,
    body_figure_ids: list[str] | None = None,
    body_figure_items: list = None,
) -> dict:
    return {
        "sections": {
            "background": "bg",
            "summary": "sum",
            "detailed_description": "dd",
        },
        "claims": {
            "count": claims_count,
            "items": [f"{i}. claim" for i in range(1, claims_count + 1)],
        },
        "figures": {
            "figure_reference_count": len(body_figure_ids or []),
            "figure_ids": body_figure_ids or [],
            "items": body_figure_items or [],
        },
        "qa": {"warnings": [], "info": {}},
    }


def test_assemble_happy_path_no_mismatch_warnings():
    front = _base_front(expected_claims=16, expected_sheets=4)

    figures_flat = [
        {
            "figure_number": 1,
            "subfigure_id": None,
            "sheet_index": 0,
            "pdf_page_index": 2,
            "label_bbox_norm": [0.1, 0.1, 0.2, 0.2],
            "crop_bbox_norm": [0.0, 0.0, 1.0, 1.0],
            "confidence": 0.9,
            "source": "detector",
            "label": "FIG. 1",
            "export": {"png_path": "sheet_001_fig_001.png"},
        },
        {
            "figure_number": 2,
            "subfigure_id": "A",
            "sheet_index": 1,
            "pdf_page_index": 3,
            "label_bbox_norm": [0.1, 0.1, 0.2, 0.2],
            "crop_bbox_norm": [0.0, 0.0, 1.0, 1.0],
            "confidence": 0.95,
            "source": "detector",
            "label": "FIG. 2A",
            "export": {"png_path": "sheet_002_fig_002A.png"},
        },
    ]
    drawings = _base_drawings(figures_flat)

    # Body returns figure designators (NOT FIG_*)
    body = _base_body(claims_count=16, body_figure_ids=["1", "2A"])

    out = assemble_parsed_patent(
        pdf_path="dummy.pdf",
        front_matter=front,
        drawing_result=drawings,
        body_result=body,
    )

    assert out["consistency"]["claims"]["match"] is True
    assert out["consistency"]["figures"]["missing_in_drawings"] == []
    assert out["consistency"]["figures"]["missing_in_body"] == []

    assert "claims_count_mismatch" not in out["qa"]["warnings"]
    assert "figure_ids_missing_in_drawings" not in out["qa"]["warnings"]
    assert "figure_ids_missing_in_body" not in out["qa"]["warnings"]

    # Ensure canonicalization happened
    assert out["body"]["figures"]["figure_ids_canonical"] == ["FIG_1", "FIG_2A"]


def test_claims_count_mismatch_warns_and_records_info():
    front = _base_front(expected_claims=16, expected_sheets=4)

    drawings = _base_drawings(
        figures_flat=[
            {
                "figure_number": 1,
                "subfigure_id": None,
                "sheet_index": 0,
                "pdf_page_index": 2,
                "label_bbox_norm": None,
                "crop_bbox_norm": None,
                "confidence": 0.9,
                "source": "detector",
                "label": "FIG. 1",
                "export": {"png_path": None},
            }
        ]
    )

    body = _base_body(claims_count=15, body_figure_ids=["1"])

    out = assemble_parsed_patent(
        pdf_path="dummy.pdf",
        front_matter=front,
        drawing_result=drawings,
        body_result=body,
    )

    assert "claims_count_mismatch" in out["qa"]["warnings"]
    assert out["qa"]["info"]["claims_expected"] == 16
    assert out["qa"]["info"]["claims_actual"] == 15
    assert out["qa"]["info"]["claims_delta"] == -1


def test_missing_in_drawings_when_body_references_unseen_figure():
    front = _base_front(expected_claims=16, expected_sheets=4)

    drawings = _base_drawings(
        figures_flat=[
            {
                "figure_number": 1,
                "subfigure_id": None,
                "sheet_index": 0,
                "pdf_page_index": 2,
                "label_bbox_norm": None,
                "crop_bbox_norm": None,
                "confidence": 0.9,
                "source": "detector",
                "label": "FIG. 1",
                "export": {"png_path": None},
            }
        ]
    )

    # Body references 2 (not present in drawings)
    body = _base_body(claims_count=16, body_figure_ids=["1", "2"])

    out = assemble_parsed_patent(
        pdf_path="dummy.pdf",
        front_matter=front,
        drawing_result=drawings,
        body_result=body,
    )

    assert "figure_ids_missing_in_drawings" in out["qa"]["warnings"]
    assert out["consistency"]["figures"]["missing_in_drawings"] == ["FIG_2"]
    assert out["qa"]["info"]["figure_ids_missing_in_drawings"] == ["FIG_2"]


def test_missing_in_body_when_drawings_have_unreferenced_figures():
    front = _base_front(expected_claims=16, expected_sheets=4)

    drawings = _base_drawings(
        figures_flat=[
            {
                "figure_number": 1,
                "subfigure_id": None,
                "sheet_index": 0,
                "pdf_page_index": 2,
                "label_bbox_norm": None,
                "crop_bbox_norm": None,
                "confidence": 0.9,
                "source": "detector",
                "label": "FIG. 1",
                "export": {"png_path": None},
            },
            {
                "figure_number": 2,
                "subfigure_id": "B",
                "sheet_index": 0,
                "pdf_page_index": 2,
                "label_bbox_norm": None,
                "crop_bbox_norm": None,
                "confidence": 0.9,
                "source": "detector",
                "label": "FIG. 2B",
                "export": {"png_path": None},
            },
        ]
    )

    # Body references only 1
    body = _base_body(claims_count=16, body_figure_ids=["1"])

    out = assemble_parsed_patent(
        pdf_path="dummy.pdf",
        front_matter=front,
        drawing_result=drawings,
        body_result=body,
    )

    assert "figure_ids_missing_in_body" in out["qa"]["warnings"]
    assert out["consistency"]["figures"]["missing_in_body"] == ["FIG_2B"]
    assert out["qa"]["info"]["figure_ids_missing_in_body"] == ["FIG_2B"]


def test_duplicate_figure_detections_warn_and_best_is_high_confidence():
    front = _base_front(expected_claims=16, expected_sheets=4)

    figures_flat = [
        {
            "figure_number": 1,
            "subfigure_id": None,
            "sheet_index": 0,
            "pdf_page_index": 2,
            "label_bbox_norm": None,
            "crop_bbox_norm": None,
            "confidence": 0.40,
            "source": "detector",
            "label": "FIG. 1",
            "export": {"png_path": "low.png"},
        },
        {
            "figure_number": 1,
            "subfigure_id": None,
            "sheet_index": 1,
            "pdf_page_index": 3,
            "label_bbox_norm": None,
            "crop_bbox_norm": None,
            "confidence": 0.95,
            "source": "detector",
            "label": "FIG. 1",
            "export": {"png_path": "high.png"},
        },
    ]
    drawings = _base_drawings(figures_flat)

    # Body references 1
    body = _base_body(claims_count=16, body_figure_ids=["1"])

    out = assemble_parsed_patent(
        pdf_path="dummy.pdf",
        front_matter=front,
        drawing_result=drawings,
        body_result=body,
    )

    assert "figure_duplicate_detections" in out["qa"]["warnings"]
    assert out["qa"]["info"]["figure_duplicate_ids"] == ["FIG_1"]

    best = out["drawings"]["figures_index"]["FIG_1"]["best"]
    assert best["export"]["png_path"] == "high.png"
    assert best["confidence"] == 0.95


def test_body_figure_ids_canonicalize_from_text_items_and_designators():
    front = _base_front(expected_claims=16, expected_sheets=4)

    drawings = _base_drawings(
        figures_flat=[
            {
                "figure_number": 2,
                "subfigure_id": "A",
                "sheet_index": 0,
                "pdf_page_index": 2,
                "label_bbox_norm": None,
                "crop_bbox_norm": None,
                "confidence": 0.9,
                "source": "detector",
                "label": "FIG. 2A",
                "export": {"png_path": None},
            }
        ]
    )

    # Body provides non-canonical forms; assembler should normalize to FIG_2A
    body = _base_body(
        claims_count=16,
        body_figure_ids=["2a", "  2A  "],
        body_figure_items=["In FIG. 2A, the system ..."],
    )

    out = assemble_parsed_patent(
        pdf_path="dummy.pdf",
        front_matter=front,
        drawing_result=drawings,
        body_result=body,
    )

    assert out["body"]["figures"]["figure_ids_canonical"] == ["FIG_2A"]
    assert out["consistency"]["figures"]["missing_in_drawings"] == []
    assert out["consistency"]["figures"]["missing_in_body"] == []
