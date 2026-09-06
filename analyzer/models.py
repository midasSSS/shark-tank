from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(StrictModel):
    claim: str
    value: float | None = None
    unit: str = ""
    period: str = ""
    definition: str = ""
    source_id: str
    quote: str
    status: Literal["reported", "corroborated", "assumption"] = "reported"


class Evidence(StrictModel):
    facts: list[Fact] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class Economics(StrictModel):
    supported: bool = False
    instrument: Literal["simple_equity", "post_money_safe", "unsupported"] = "unsupported"
    currency: str = "USD"
    entry_post_money: float | None = None
    investment: float | None = None
    retained_fraction: float | None = None
    fee_fraction: float | None = None
    carry_fraction: float | None = None
    holding_years: float | None = None
    exit_downside: float | None = None
    exit_base: float | None = None
    exit_upside: float | None = None
    source_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EvidenceReview(StrictModel):
    identity_confirmed: bool
    material_gaps: list[str]
    unresolved_conflicts: list[str]
    rationale: str


class PathAssessment(StrictModel):
    qualifies: bool
    reasons: list[str]
    source_ids: list[str]
    required_outcome: str
    main_risk: str
    blockers: list[str] = Field(default_factory=list)


class Decision(StrictModel):
    reasons: list[str] = Field(min_length=1, max_length=3)
    main_risk: str
    confidence: Literal["high", "medium", "low"]
    confidence_reason: str
    source_ids: list[str]
