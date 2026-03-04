from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Set

from pydantic import BaseModel, Field, ConfigDict

from doc_extractor.diagnostics import Diagnostics, Issue


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class FieldValue:
    raw: str = ""
    confidence: Confidence = Confidence.LOW
    issues: list[Issue] = field(default_factory=list)


@dataclass
class TextValue(FieldValue):
    text: str = ""


class TokenField(BaseModel):
    """
    For things like patent ids, application ids, IPC, USCL, prior-art ids.
    """

    model_config = ConfigDict(frozen=True)

    raw: str = ""
    tokens: Set[str] = Field(default_factory=set)
    primary: Optional[str] = None
    issues: List[Issue] = Field(default_factory=list)


class TextField(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: str = ""
    text: str = ""
    issues: List[Issue] = Field(default_factory=list)


class PeopleField(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: str = ""
    people: List[str] = Field(default_factory=list)
    issues: List[Issue] = Field(default_factory=list)


class DateField(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw: str = ""
    # keep as string initially; later you can switch to date
    value: Optional[str] = None
    issues: List[Issue] = Field(default_factory=list)


# --- grouped semantic models ---
class Identification(BaseModel):
    model_config = ConfigDict(frozen=True)

    publication_id: TokenField = Field(
        default_factory=TokenField
    )  # from (10)/(12)/header parse
    kind: Optional[str] = None  # optional; often part of publication_id token


class Application(BaseModel):
    model_config = ConfigDict(frozen=True)

    application_number: TokenField = Field(
        default_factory=TokenField
    )  # (21), also PCT in (86)
    filing_date: DateField = Field(default_factory=DateField)  # (22)


class Dates(BaseModel):
    model_config = ConfigDict(frozen=True)

    date_grant_made_public: DateField = Field(default_factory=DateField)  # (45)


class Technical(BaseModel):
    model_config = ConfigDict(frozen=True)

    ipc: TokenField = Field(default_factory=TokenField)  # (51)
    uscl: TokenField = Field(default_factory=TokenField)  # (52)
    title: TextField = Field(default_factory=TextField)  # (54)
    prior_art: TokenField = Field(default_factory=TokenField)  # (56) tokenized patents
    abstract: TextField = Field(default_factory=TextField)  # (57)
    field_of_search: TokenField = Field(
        default_factory=TokenField
    )  # (58) tokens/classes


class References(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Keep as TokenField because these often contain application/patent numbers
    continuation: TokenField = Field(
        default_factory=TokenField
    )  # (63) etc (you can split later)
    related: TokenField = Field(
        default_factory=TokenField
    )  # catch-all for (60)/(61-67)


class Parties(BaseModel):
    model_config = ConfigDict(frozen=True)

    applicants: PeopleField = Field(default_factory=PeopleField)  # (71)
    inventors: PeopleField = Field(default_factory=PeopleField)  # (72)/(75)
    assignee: TextField = Field(default_factory=TextField)  # (73)
    attorney_agent: PeopleField = Field(default_factory=PeopleField)  # (74)


class ParsedFrontMatter(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    raw_inids: Dict[str, str] = Field(
        default_factory=dict
    )  # store by code string "54" to avoid Enum serialization pain
    num_sheets: int = 0

    # You can either store your existing Diagnostics or this model; pick one.
    diagnostics: Diagnostics = Field(default_factory=Diagnostics)

    identification: Identification = Field(default_factory=Identification)
    application: Application = Field(default_factory=Application)
    dates: Dates = Field(default_factory=Dates)
    technical: Technical = Field(default_factory=Technical)
    references: References = Field(default_factory=References)
    parties: Parties = Field(default_factory=Parties)
