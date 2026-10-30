from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


Category = Literal["returns", "damaged_item", "shipping", "other"]
Decision = Literal["policy_supported", "needs_information", "human_review"]


class TriageFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days_since_delivery: StrictInt | None = Field(default=None, ge=0)
    days_overdue: StrictInt | None = Field(default=None, ge=0)
    unused: StrictBool | None = None
    final_sale: StrictBool | None = None
    photo_provided: StrictBool | None = None


class TriageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ticket_id: str = Field(min_length=1, max_length=128)
    order_ref: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=5000)
    facts: TriageFacts = Field(default_factory=TriageFacts)


class Citation(BaseModel):
    policy_id: str
    excerpt: str


class ModelStatus(BaseModel):
    provider: str
    used: bool
    fallback: bool


class TriageResponse(BaseModel):
    ticket_id: str
    request_id: str
    retailer: str
    category: Category
    decision: Decision
    next_action: str
    customer_response: str
    citations: list[Citation]
    missing_information: list[str]
    fact_sources: dict[str, Literal["erp", "client"]]
    discrepancies: list[dict[str, object]]
    model: ModelStatus
    latency_ms: int = Field(ge=0)