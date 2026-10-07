"""Request/response contracts (Pydantic v2). Validation of both inputs and outputs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator

Category = Literal["returns", "damaged_item", "shipping", "other"]
Decision = Literal["policy_supported", "needs_information", "human_review"]
Retailer = Literal["northstar", "cedar"]
FactSource = Literal["erp", "client"]


class ClientFacts(BaseModel):
    """Client-supplied hints. Never authoritative — reconciled against the ERP."""

    model_config = ConfigDict(extra="ignore")

    days_since_delivery: StrictInt | None = Field(default=None, ge=0, le=3650)
    days_overdue: StrictInt | None = Field(default=None, ge=0, le=3650)
    unused: StrictBool | None = None
    final_sale: StrictBool | None = None
    photo_provided: StrictBool | None = None


class TriageRequest(BaseModel):
    # extra="ignore": a client-supplied "retailer" field is silently dropped — identity
    # comes from the API key only.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    ticket_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    order_ref: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    message: str = Field(min_length=1, max_length=4000)
    facts: ClientFacts = Field(default_factory=ClientFacts)

    @field_validator("facts", mode="before")
    @classmethod
    def _null_facts(cls, v):
        return {} if v is None else v

    @field_validator("order_ref", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class Citation(BaseModel):
    policy_id: str
    excerpt: str


class ModelInfo(BaseModel):
    provider: str
    used: bool
    fallback: bool


class TriageResponse(BaseModel):
    ticket_id: str
    request_id: str
    retailer: Retailer
    category: Category
    decision: Decision
    next_action: str = Field(max_length=300)
    customer_response: str = Field(min_length=1, max_length=400)
    citations: list[Citation]
    missing_information: list[str]
    fact_sources: dict[str, FactSource]
    discrepancies: list[str]
    model: ModelInfo
    latency_ms: int = Field(ge=0)
