from __future__ import annotations

from typing import Optional
import re

from patent_ingest.diagnostics import Diagnostics

from .registry import INIDKind, ParsePolicy
from .parser import ParsedFrontMatter
from .clean import (
    clean_title,
    clean_abstract,
    clean_assignee,
    clean_inventors,
    clean_attorney,
    clean_application_number,
    clean_filing_date,
    clean_grant_date,
    clean_inid_text,
    split_abstract_tail,
)

from .tokens import (
    extract_patent_id_tokens,
    extract_application_id_tokens,
    extract_ipc_tokens,
    extract_uscl_tokens,
)
from .types import (
    ParsedFrontMatterV1,
    Identification,
    Application,
    Technical,
    Parties,
    TokenField,
    TextField,
    PeopleField,
)


def _primary_or_none(tokens: set[str]) -> Optional[str]:
    if len(tokens) == 1:
        return next(iter(tokens))
    return None


def _split_people(raw: str) -> list[str]:
    """
    Conservative splitter for inventor/applicant lists.
    Do not over-normalize—OCR is messy.
    """
    s = raw.strip()
    if not s:
        return []

    # Prefer semicolons; otherwise split by newlines.
    parts = [p.strip() for p in (s.split(";") if ";" in s else s.split("\n"))]
    return [p for p in parts if p]


def parse_front_matter_semantic(
    raw: ParsedFrontMatter, *, policy: ParsePolicy
) -> ParsedFrontMatterV1:
    """
    Semantic parse v1:
      - remove INID prefixes and field labels (ABSTRACT/Assignee/Inventors/etc.)
      - populate typed Pydantic models
      - token extraction for IDs/classifications (can be expanded later)
    """
    diag = Diagnostics()
    diag.merge(raw.diagnostics)

    # --- raw_inids as stable code->raw string ---
    raw_inids: dict[str, str] = {k.value: v for k, v in raw.inid.items()}

    # --- clean text fields (strip INID, strip label) ---
    title_raw = raw.inid.get(INIDKind._54, "")
    abstract_raw = raw.inid.get(INIDKind._57, "")
    assignee_raw = raw.inid.get(INIDKind._73, "")
    inventors_raw = raw.inid.get(INIDKind._75, "")
    attorney_raw = raw.inid.get(INIDKind._74, "")

    title = clean_title(title_raw)
    abstract = clean_abstract(abstract_raw)
    abstract2, abs_meta = split_abstract_tail(abstract)
    abstract = abstract2
    if abs_meta:
        # attach to diagnostics meta for now, or store in a dedicated model field
        diag.info(
            "inid_parse.abstract_tail",
            "Split claims/drawings tail from abstract.",
            inid="57",
            **abs_meta,
        )
        claims_count = abs_meta.get("claims_count")
        drawing_sheet_count = abs_meta.get("drawing_sheets_count")
    assignee = clean_assignee(assignee_raw)
    if re.search(r"\b[A-Z]{2}\s*\(US\)\b.*\b[A-Z]{2}\s*\(US\)\b", assignee, flags=re.S):
        diag.warn(
            "inid_parse.assignee_multiple_states",
            "Assignee contains multiple state markers.",
            inid="73",
        )

    inventors_text = clean_inventors(inventors_raw)
    attorney = clean_attorney(attorney_raw)

    # --- clean app/date-ish fields (still text at this stage) ---
    app21_raw = raw.inid.get(INIDKind._21, "")
    filed22_raw = raw.inid.get(INIDKind._22, "")

    app21_clean = clean_application_number(app21_raw)
    filed22_clean = clean_filing_date(filed22_raw)

    grant45_raw = raw.inid.get(INIDKind._45, "")
    grant45_clean = clean_grant_date(grant45_raw)

    # --- IDs / tokens ---
    # Separate patent publication (10, 12) from prior publication (65)
    pub_raw = "\n".join(
        [
            raw.inid.get(INIDKind._10, ""),
            raw.inid.get(INIDKind._12, ""),
        ]
    ).strip()
    pub_tokens = extract_patent_id_tokens(pub_raw, include_bare_us=True)
    pub_primary = _primary_or_none(pub_tokens)

    # Prior publication data (65) stored separately
    prior_pub_raw = raw.inid.get(INIDKind._65, "").strip()
    prior_pub_tokens = extract_patent_id_tokens(prior_pub_raw, include_bare_us=True) if prior_pub_raw else []
    prior_pub_primary = _primary_or_none(prior_pub_tokens)

    app_raw = "\n".join([app21_clean, raw.inid.get(INIDKind._86, "")]).strip()
    app_tokens = extract_application_id_tokens(app_raw)
    app_primary = _primary_or_none(app_tokens)

    ipc_raw = "\n".join(
        [raw.inid.get(INIDKind._51, ""), raw.inid.get(INIDKind._58, "")]
    ).strip()
    ipc_tokens = extract_ipc_tokens(ipc_raw)
    uscl_raw = raw.inid.get(INIDKind._52, "")
    fos_raw = raw.inid.get(INIDKind._58, "")
    uscl_tokens = extract_uscl_tokens(uscl_raw)
    fos_tokens = extract_uscl_tokens(fos_raw)

    refs_raw = raw.inid.get(INIDKind._56, "")
    refs_clean = clean_inid_text(refs_raw)  # remove "(56)" but keep internal structure
    ref_tokens = extract_patent_id_tokens(refs_clean, include_bare_us=True)

    people = _split_people(inventors_text)
    if people and any(p.endswith(",") for p in people):
        diag.warn(
            "inid_parse.inventor_truncated",
            "Inventor entry appears truncated (ends with comma).",
            inid="75",
            sample=[p for p in people if p.endswith(",")][:2],
        )

    # --- semantic-level requiredness (optional, can be expanded) ---
    if policy.require_title and not title:
        diag.error(
            "inid_parse.missing_title_text",
            "Title (54) empty after cleaning.",
            inid="54",
        )
    if policy.require_pub_id and not pub_tokens:
        diag.error(
            "inid_parse.missing_pub_id_token",
            "No publication/patent id tokens parsed.",
            inid="10",
        )

    return ParsedFrontMatterV1(
        raw_inids=raw_inids,
        pages=list(raw.pages),
        diagnostics=diag,
        identification=Identification(
            publication=TokenField(raw=pub_raw, tokens=pub_tokens, primary=pub_primary),
            prior_publication=TokenField(raw=prior_pub_raw, tokens=prior_pub_tokens, primary=prior_pub_primary),
        ),
        application=Application(
            application_number=TokenField(
                raw=app_raw, tokens=app_tokens, primary=app_primary
            ),
            filing_date=TextField(raw=filed22_raw, text=filed22_clean),
            grant_date=TextField(raw=grant45_raw, text=grant45_clean),
        ),
        technical=Technical(
            title=TextField(raw=title_raw, text=title),
            abstract=TextField(raw=abstract_raw, text=abstract),
            ipc=TokenField(
                raw=ipc_raw, tokens=ipc_tokens, primary=_primary_or_none(ipc_tokens)
            ),
            uscl=TokenField(
                raw=uscl_raw, tokens=uscl_tokens, primary=_primary_or_none(uscl_tokens)
            ),
            references=TokenField(raw=refs_clean, tokens=ref_tokens, primary=None),
            field_of_search=TokenField(raw=fos_raw, tokens=fos_tokens, primary=None),
            claims_count=claims_count if "claims_count" in abs_meta else None,
            drawing_sheets_count=drawing_sheet_count
            if "drawing_sheets_count" in abs_meta
            else None,
        ),
        parties=Parties(
            inventors=PeopleField(raw=inventors_raw, people=people),
            assignee=TextField(raw=assignee_raw, text=assignee),
            attorney_agent=TextField(raw=attorney_raw, text=attorney),
            # if you later add attorney field, Parties can grow
        ),
    )
