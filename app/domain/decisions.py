from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import Decision
from app.repositories.policy_repository import Policy, PolicyRepository


RETURN_WINDOWS = {"northstar": 30, "cedar": 14}
DAMAGE_PHOTO_WINDOW_DAYS = 7
SHIPPING_INVESTIGATION_DAYS = {"northstar": 6, "cedar": 4}


@dataclass(frozen=True)
class PolicyOutcome:
    decision: Decision
    next_action: str
    missing_information: tuple[str, ...] = ()
    citation_excerpt: str | None = None
    citation_sentence_index: int = 0


def decide(
    retailer: str,
    category: str,
    facts: dict[str, object],
    policy: Policy | None,
) -> PolicyOutcome:
    if category == "other":
        return PolicyOutcome("human_review", "A support specialist must review this request.")
    if policy is None:
        return PolicyOutcome("human_review", "A support specialist must review this request.")

    if category == "returns":
        final_sale = facts.get("final_sale")
        if final_sale is True:
            return PolicyOutcome(
                "policy_supported",
                "This final-sale item is not eligible for return.",
                citation_sentence_index=1,
            )
        missing = tuple(
            field
            for field in ("final_sale", "unused", "days_since_delivery")
            if facts.get(field) is None
        )
        if missing:
            return PolicyOutcome(
                "needs_information",
                "Support must verify the missing order details before confirming return eligibility.",
                missing,
            )
        if facts["unused"] is not True:
            return PolicyOutcome(
                "policy_supported",
                "This item does not meet the unused-item requirement for a return.",
                citation_sentence_index=0,
            )
        if int(facts["days_since_delivery"]) > RETURN_WINDOWS[retailer]:
            return PolicyOutcome(
                "policy_supported",
                f"This item is outside the {RETURN_WINDOWS[retailer]}-day return window and is not eligible under the supplied policy.",
                citation_sentence_index=0,
            )
        return PolicyOutcome(
            "policy_supported",
            "The order details meet the return policy. Please contact support to arrange the return.",
            citation_sentence_index=0,
        )

    if category == "damaged_item":
        if retailer == "cedar":
            return PolicyOutcome(
                "human_review",
                "A support specialist must review this damaged-item complaint; no refund or replacement is promised.",
                citation_excerpt=policy.text,
            )
        days = facts.get("days_since_delivery")
        if days is None:
            return PolicyOutcome(
                "needs_information",
                "Support must verify the delivery date before applying the damage policy.",
                ("days_since_delivery",),
            )
        if int(days) > DAMAGE_PHOTO_WINDOW_DAYS:
            return PolicyOutcome(
                "human_review",
                "A support specialist must review this later damage report.",
                citation_sentence_index=1,
            )
        photo = facts.get("photo_provided")
        if photo is not True:
            return PolicyOutcome(
                "needs_information",
                "Please provide a photo of the damage before a replacement can be considered.",
                ("photo_provided",),
                citation_sentence_index=0,
            )
        return PolicyOutcome(
            "policy_supported",
            "A support specialist can review the photo before deciding whether a replacement is appropriate.",
            citation_sentence_index=0,
        )

    if category == "shipping":
        days_overdue = facts.get("days_overdue")
        if days_overdue is None:
            return PolicyOutcome(
                "needs_information",
                "Support must verify the promised delivery date before checking investigation eligibility.",
                ("days_overdue",),
            )
        if int(days_overdue) >= SHIPPING_INVESTIGATION_DAYS[retailer]:
            return PolicyOutcome(
                "policy_supported",
                "A carrier investigation is eligible. This does not automatically authorise a refund.",
                citation_excerpt=policy.text,
            )
        return PolicyOutcome(
            "policy_supported",
            "This shipment has not passed the policy threshold for a carrier investigation.",
            citation_sentence_index=0,
        )

    return PolicyOutcome("human_review", "A support specialist must review this request.")