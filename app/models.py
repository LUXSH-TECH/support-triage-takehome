from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["returns", "damaged_item", "shipping", "other"]
Decision = Literal["policy_supported", "needs_information", "human_review"]


class Facts(BaseModel):
    days_since_delivery: int | None = Field(None, ge=0)
    days_overdue: int | None = Field(None, ge=0)
    unused: bool | None = None
    final_sale: bool | None = None
    photo_provided: bool | None = None


class TriageRequest(BaseModel):
    ticket_id: str = Field(min_length=1, max_length=64)
    order_ref: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    facts: Facts = Field(default_factory=Facts)


class Citation(BaseModel):
    policy_id: str
    excerpt: str


class Discrepancy(BaseModel):
    fact: str
    client: str | int | bool | None
    erp: str | int | bool | None


class ModelInfo(BaseModel):
    provider: str
    used: bool
    fallback: bool


class TriageResponse(BaseModel):
    ticket_id: str
    request_id: str
    retailer: Literal["northstar", "cedar"]
    category: Category
    decision: Decision
    next_action: str
    customer_response: str = Field(max_length=400)
    citations: list[Citation]
    missing_information: list[str]
    fact_sources: dict[str, Literal["erp", "client"]]
    discrepancies: list[Discrepancy]
    model: ModelInfo
    latency_ms: int