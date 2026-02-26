from __future__ import annotations

from typing import Any, Optional, Set, Dict, List
from pydantic import BaseModel, ConfigDict, Field

from patent_ingest.diagnostics import Diagnostics, _canon_diagnostics


class TokenField(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw: str = ""
    tokens: Set[str] = Field(default_factory=set)
    primary: Optional[str] = None


def _canon_token_field(tf: TokenField) -> Dict[str, Any]:
    return {
        "primary": tf.primary or None,
        "tokens": sorted(tf.tokens) if tf.tokens else [],
        # raw is usually not needed for canonical consumers; keep only if you want it
    }


class TextField(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw: str = ""
    text: str = ""


def _canon_text_field(tf: TextField) -> Optional[str]:
    # canonical prefers the cleaned text; return None if empty
    t = (tf.text or "").strip()
    return t or None


class PeopleField(BaseModel):
    model_config = ConfigDict(frozen=True)
    raw: str = ""
    people: List[str] = Field(default_factory=list)


def _canon_people_field(pf: PeopleField) -> List[str]:
    return [p.strip() for p in (pf.people or []) if p and p.strip()]


class Identification(BaseModel):
    model_config = ConfigDict(frozen=True)
    publication: TokenField = Field(default_factory=TokenField)
    prior_publication: TokenField = Field(default_factory=TokenField)


class Application(BaseModel):
    model_config = ConfigDict(frozen=True)
    application_number: TokenField = Field(default_factory=TokenField)
    filing_date: TextField = Field(default_factory=TextField)  # keep as text for now
    grant_date: TextField = Field(default_factory=TextField)  # keep as text for now


class Technical(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: TextField = Field(default_factory=TextField)
    abstract: TextField = Field(default_factory=TextField)
    ipc: TokenField = Field(default_factory=TokenField)
    uscl: TokenField = Field(default_factory=TokenField)
    references: TokenField = Field(default_factory=TokenField)  # (56) patent-id tokens
    field_of_search: TokenField = Field(default_factory=TokenField)
    claims_count: int | None
    drawing_sheets_count: int | None


class Parties(BaseModel):
    model_config = ConfigDict(frozen=True)
    inventors: PeopleField = Field(default_factory=PeopleField)
    assignee: TextField = Field(default_factory=TextField)
    attorney_agent: TextField = Field(default_factory=TextField)


class ParsedFrontMatterV1(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    raw_inids: Dict[str, str] = Field(default_factory=dict)  # code string -> raw
    pages: List[int] = Field(default_factory=list)
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)

    identification: Identification = Field(default_factory=Identification)
    application: Application = Field(default_factory=Application)
    technical: Technical = Field(default_factory=Technical)
    parties: Parties = Field(default_factory=Parties)

    @property
    def num_sheets(self) -> int:
        return len(self.pages)

    def canonical(self, *, include_debug: bool = False) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schema_version": "front_matter.v1",
            "pages": list(self.pages),
            "identification": {
                "publication": _canon_token_field(self.identification.publication),
                "prior_publication": _canon_token_field(self.identification.prior_publication),
            },
            "application": {
                "application_number": _canon_token_field(
                    self.application.application_number
                ),
                "filing_date": _canon_text_field(self.application.filing_date),
                "grant_date": _canon_text_field(self.application.grant_date),
            },
            "technical": {
                "title": _canon_text_field(self.technical.title),
                "abstract": _canon_text_field(self.technical.abstract),
                "ipc": _canon_token_field(self.technical.ipc),
                "uscl": _canon_token_field(self.technical.uscl),
                "field_of_search": _canon_token_field(self.technical.field_of_search),
                "references": _canon_token_field(self.technical.references),
                "claims_count": self.technical.claims_count,
                "drawing_sheets_count": self.technical.drawing_sheets_count,
            },
            "parties": {
                "inventors": _canon_people_field(self.parties.inventors),
                "assignee": _canon_text_field(self.parties.assignee),
                "attorney_agent": _canon_text_field(self.parties.attorney_agent),
            },
            "diagnostics": _canon_diagnostics(self.diagnostics),
        }

        # convenience top-level shortcuts (makes downstream simpler)
        out["publication_id"] = self.identification.publication.primary or None
        out["publication_tokens"] = (
            sorted(self.identification.publication.tokens)
            if self.identification.publication.tokens
            else []
        )

        if include_debug:
            out["debug"] = {
                "raw_inids": dict(self.raw_inids),
                # If you want full raw fields too:
                "raw_fields": {
                    "publication": self.identification.publication.raw,
                    "application_number": self.application.application_number.raw,
                    "filing_date": self.application.filing_date.raw,
                    "title": self.technical.title.raw,
                    "abstract": self.technical.abstract.raw,
                    "ipc": self.technical.ipc.raw,
                    "uscl": self.technical.uscl.raw,
                    "field_of_search": self.technical.field_of_search.raw,
                    "references": self.technical.references.raw,
                    "inventors": self.parties.inventors.raw,
                    "assignee": self.parties.assignee.raw,
                    "attorney_agent": self.parties.attorney_agent.raw,
                },
            }

        return out
