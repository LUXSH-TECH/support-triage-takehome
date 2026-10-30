from __future__ import annotations

from dataclasses import dataclass


AUTHORITATIVE_FIELDS = (
    "days_since_delivery",
    "days_overdue",
    "unused",
    "final_sale",
)


@dataclass(frozen=True)
class Reconciliation:
    facts: dict[str, object]
    fact_sources: dict[str, str]
    discrepancies: list[dict[str, object]]


def reconcile(
    erp_facts: dict[str, object | None], client_facts: dict[str, object | None]
) -> Reconciliation:
    facts: dict[str, object] = {}
    sources: dict[str, str] = {}
    discrepancies: list[dict[str, object]] = []

    for field in AUTHORITATIVE_FIELDS:
        verified = erp_facts.get(field)
        claimed = client_facts.get(field)
        if verified is None:
            continue
        facts[field] = verified
        sources[field] = "erp"
        if claimed is not None and claimed != verified:
            discrepancies.append(
                {"field": field, "client_value": claimed, "erp_value": verified}
            )

    photo_provided = client_facts.get("photo_provided")
    if photo_provided is not None:
        facts["photo_provided"] = photo_provided
        sources["photo_provided"] = "client"

    return Reconciliation(facts, sources, discrepancies)