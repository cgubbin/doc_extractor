from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
import re


FIG_SINGLE_PAT = re.compile(r"\bFIG\.?\s*(\d+)\s*([A-Za-z])?\b", re.IGNORECASE)


FIG_DESIGNATOR_PAT = re.compile(r"^\s*(\d+)\s*([A-Za-z])?\s*$")


def canonical_fig_id_from_designator(des: str) -> Optional[str]:
    """
    Accepts body-style IDs: '1', '2A', ' 12 b ' and returns 'FIG_1', 'FIG_2A', 'FIG_12B'.
    """
    if des is None:
        return None
    s = str(des).strip()
    if not s:
        return None

    # already canonical
    if s.upper().startswith("FIG_"):
        return s.upper()

    m = FIG_DESIGNATOR_PAT.match(s)
    if not m:
        return None

    n = int(m.group(1))
    suf = (m.group(2) or "").upper()
    return f"FIG_{n}{suf}"


def canonical_fig_id(figure_number: Any, subfigure_id: Any = None) -> Optional[str]:
    if figure_number is None:
        return None
    try:
        n = int(str(figure_number).strip())
    except Exception:
        return None
    suf = ""
    if subfigure_id is not None:
        s = str(subfigure_id).strip()
        if s:
            suf = s.upper()
            # keep only first alpha char
            m = re.match(r"[A-Z]", suf)
            suf = m.group(0) if m else ""
    return f"FIG_{n}{suf}"


def canonicalize_fig_label_text(label: str) -> List[str]:
    """
    Extract atomic figure IDs from text. Best effort.
    Handles simple 'FIG. 1A' occurrences. Range expansion is optional.
    """
    out: List[str] = []
    if not label:
        return out
    for m in FIG_SINGLE_PAT.finditer(label):
        n = m.group(1)
        suf = m.group(2)
        fid = canonical_fig_id(n, suf)
        if fid:
            out.append(fid)
    # de-dupe preserving order
    seen = set()
    uniq = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def _aggregate_qa(*qas: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    warnings: List[str] = []
    info: Dict[str, Any] = {}
    for qa in qas:
        if not qa:
            continue
        warnings.extend(list(qa.get("warnings") or []))
        info.update(dict(qa.get("info") or {}))
    # de-dup warnings
    seen = set()
    deduped = []
    for w in warnings:
        if w not in seen:
            seen.add(w)
            deduped.append(w)
    return {"warnings": deduped, "info": info}


def assemble_parsed_patent(
    *,
    pdf_path: str,
    front_matter: dict,
    drawing_result: dict,
    body_result: dict,
) -> dict:
    # --- Pull expected counts ---
    reported_counts = front_matter.get("reported_counts") or {}
    expected_claims = reported_counts.get("reported_claim_count")
    expected_sheets = reported_counts.get("reported_drawing_sheet_count")

    # --- Drawings: normalize figures_flat into an index by canonical ID ---
    figures_flat = drawing_result.get("figures") or []
    by_id: Dict[str, List[dict]] = defaultdict(list)

    for it in figures_flat:
        fid = canonical_fig_id(it.get("figure_number"), it.get("subfigure_id"))
        if not fid:
            continue
        rec = dict(it)
        rec["figure_id"] = fid
        by_id[fid].append(rec)

    # Choose a "best" detection per figure_id
    def pick_best(items: List[dict]) -> dict:
        # higher confidence first, then earlier page, then earlier sheet
        def key(x: dict) -> Tuple[float, int, int]:
            conf = x.get("confidence")
            conf = float(conf) if conf is not None else -1.0
            page = int(x.get("pdf_page_index") or 10**9)
            sheet = int(x.get("sheet_index") or 10**9)
            return (-conf, page, sheet)

        return sorted(items, key=key)[0]

    drawings_index = {}
    duplicates = []
    for fid, items in by_id.items():
        if len(items) > 1:
            duplicates.append(fid)
        drawings_index[fid] = {
            "best": pick_best(items),
            "all": items,
        }

    drawing_ids = set(drawings_index.keys())

    # --- Body: normalize figure ids ---
    body_fig_ids_raw = body_result.get("figures", {}).get("figure_ids") or []
    body_ids = set()

    for x in body_fig_ids_raw:
        fid = canonical_fig_id_from_designator(x)
        if fid:
            body_ids.add(fid)

    # If body parser also returns "items", optionally mine them for additional ids
    body_fig_items = body_result.get("figures", {}).get("items") or []
    for item in body_fig_items:
        # If item is a string, parse it; if dict, inspect likely fields
        if isinstance(item, str):
            for fid in canonicalize_fig_label_text(item):
                body_ids.add(fid)
        elif isinstance(item, dict):
            txt = item.get("text") or item.get("label") or ""
            for fid in canonicalize_fig_label_text(str(txt)):
                body_ids.add(fid)

    # --- Consistency checks ---
    warnings = []
    info: Dict[str, Any] = {}

    # Claims
    actual_claims = body_result.get("claims", {}).get("count")
    if isinstance(expected_claims, int) and isinstance(actual_claims, int):
        if expected_claims != actual_claims:
            warnings.append("claims_count_mismatch")
            info["claims_expected"] = expected_claims
            info["claims_actual"] = actual_claims
            info["claims_delta"] = actual_claims - expected_claims

    # Figures
    missing_in_drawings = sorted(body_ids - drawing_ids)
    missing_in_body = sorted(drawing_ids - body_ids)

    if missing_in_drawings:
        warnings.append("figure_ids_missing_in_drawings")
        info["figure_ids_missing_in_drawings"] = missing_in_drawings

    # This one may be informational (figures can exist but never referenced)
    if missing_in_body:
        warnings.append("figure_ids_missing_in_body")
        info["figure_ids_missing_in_body"] = missing_in_body

    if duplicates:
        warnings.append("figure_duplicate_detections")
        info["figure_duplicate_ids"] = sorted(duplicates)

    # Optional: sheet count check
    sheet_count = drawing_result.get("drawing_sheets", {}).get("sheet_count") or drawing_result.get(
        "sheet_count"
    )
    if (
        isinstance(expected_sheets, int)
        and isinstance(sheet_count, int)
        and expected_sheets != sheet_count
    ):
        warnings.append("drawing_sheet_count_mismatch")
        info["drawing_sheets_expected"] = expected_sheets
        info["drawing_sheets_actual"] = sheet_count

    # Aggregate QA from components + consistency
    qa = _aggregate_qa(front_matter.get("qa"), drawing_result.get("qa"), body_result.get("qa"))
    qa["warnings"].extend([w for w in warnings if w not in qa["warnings"]])
    qa["info"].update(info)

    # --- Compose final object ---
    sections = body_result.get("sections") or {}
    # Ensure required keys exist (best effort)

    for k in ("background", "summary", "detailed_description"):
        sections.setdefault(k, "")

    return {
        "meta": {
            "pdf_path": pdf_path,
            "reported_counts": {
                "expected_claim_count": expected_claims,
                "expected_drawing_sheet_count": expected_sheets,
                "expected_figure_count_from_drawings": len(drawing_ids),
            },
            "extracted_counts": {
                "claims_count": actual_claims,
                "figure_ids_count_body": len(body_ids),
                "figure_ids_count_drawings": len(drawing_ids),
            },
        },
        "front_matter": front_matter,
        "drawings": {
            "figures_flat": figures_flat,  # keep raw list for traceability
            "figures_index": drawings_index,  # keyed by FIG_#
        },
        "body": {
            "sections": sections,
            "claims": body_result.get("claims"),
            "figures": {
                **(body_result.get("figures") or {}),
                "figure_ids_canonical": sorted(body_ids),
            },
        },
        "consistency": {
            "claims": {
                "expected": expected_claims,
                "actual": actual_claims,
                "match": (expected_claims == actual_claims)
                if (isinstance(expected_claims, int) and isinstance(actual_claims, int))
                else None,
            },
            "figures": {
                "drawing_ids": sorted(drawing_ids),
                "body_ids": sorted(body_ids),
                "missing_in_drawings": missing_in_drawings,
                "missing_in_body": missing_in_body,
                "duplicates": sorted(duplicates),
            },
        },
        "qa": qa,
    }
