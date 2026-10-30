from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DraftCitation:
    policy_id: str
    excerpt: str


@dataclass(frozen=True)
class ModelDraft:
    response: str
    citations: tuple[DraftCitation, ...]


@dataclass(frozen=True)
class ModelContext:
    retailer: str
    ticket_message: str
    category: str
    decision: str
    next_action: str
    policy_id: str | None
    policy_text: str | None
    citation_excerpt: str | None
    verified_facts: dict[str, object]
    missing_information: tuple[str, ...]
    has_discrepancies: bool


class ModelProvider(Protocol):
    name: str

    def draft(self, context: ModelContext) -> ModelDraft:
        ...