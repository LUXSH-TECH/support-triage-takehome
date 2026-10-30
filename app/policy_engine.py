"""Deterministic policy enforcement — the only place decisions are made.

The LLM never decides eligibility. Given the category, the retailer's policy row
(retrieved from the DB, already retailer-scoped) and reconciled facts, this module
returns a decision, the next action, the exact policy sentences that justify it, and
a deterministic draft that the model may only rephrase.

Numeric thresholds live in ``RULES`` and are checked against the policy wording by
``tests/test_rules_and_guardrails.py::test_rule_thresholds_match_policy_text`` so a policy text change cannot silently
drift from the code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .db import Policy
from .facts import ResolvedFacts


@dataclass(frozen=True)
class RetailerRules:
    return_window_days: int  # eligible while days_since_delivery <= this
    damage_photo_window_days: int | None  # None => every damage report needs human review
    ship_investigation_min_overdue: int  # eligible when days_overdue >= this


RULES: dict[str, RetailerRules] = {
    # N-RET "within 30 days"; N-DMG "within seven days"; N-SHIP "more than five days" => >= 6
    "northstar": RetailerRules(return_window_days=30, damage_photo_window_days=7, ship_investigation_min_overdue=6),
    # C-RET "within 14 days"; C-DMG all human review; C-SHIP "more than three days" => >= 4
    "cedar": RetailerRules(return_window_days=14, damage_photo_window_days=None, ship_investigation_min_overdue=4),
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]


def excerpt(policy: Policy, index: int) -> dict[str, str]:
    """A citation whose excerpt is, by construction, a verbatim substring of the stored text."""
    s = sentences(policy.text)[index]
    assert s in policy.text
    return {"policy_id": policy.policy_id, "excerpt": s}


MISSING_LABELS = {
    "order_ref": "your order number",
    "days_since_delivery": "the date your order was delivered",
    "days_overdue": "the delivery date you were promised",
    "final_sale": "whether the item was bought as a final-sale item",
    "unused": "whether the item is unused and in its original condition",
    "photo_provided": "a photo of the damage",
}

HUMAN_REVIEW_MESSAGE = (
    "Thanks for contacting us. A member of our support team will review your request "
    "and get back to you."
)


@dataclass
class Outcome:
    decision: str
    reason: str
    next_action: str
    draft: str
    citations: list[dict[str, str]] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    used_facts: list[str] = field(default_factory=list)


# Facts only the ERP can establish. Asking the customer for them is pointless (client hints
# never fill these), so a found-but-incomplete ERP record goes to an agent instead.
ERP_ONLY_FACTS = {"days_since_delivery", "days_overdue", "final_sale"}


def needs_info(reason: str, missing: list[str], citations, used: list[str]) -> Outcome:
    erp_gaps = [m for m in missing if m in ERP_ONLY_FACTS]
    if erp_gaps and reason != "order_not_found":
        out = human(
            "erp_incomplete",
            f"Route to an agent: the ERP record is missing {', '.join(erp_gaps)}; verify the order before deciding.",
            citations,
            used,
        )
        out.missing = missing
        return out
    items = [MISSING_LABELS.get(m, m) for m in missing]
    ask = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
    return Outcome(
        decision="needs_information",
        reason=reason,
        next_action=f"Ask the customer for: {', '.join(missing)}.",
        draft=f"Thanks for getting in touch. To help with your request, could you please send us {ask}?",
        citations=citations,
        missing=missing,
        used_facts=used,
    )


def human(reason: str, next_action: str, citations=None, used=None) -> Outcome:
    return Outcome(
        decision="human_review",
        reason=reason,
        next_action=next_action,
        draft=HUMAN_REVIEW_MESSAGE,
        citations=citations or [],
        used_facts=used or [],
    )


def decide(category: str, retailer: str, policy: Policy | None, facts: ResolvedFacts) -> Outcome:
    rules = RULES[retailer]
    if category == "returns" and facts.damaged_in_erp:
        # "Damaged items follow the damaged-item policy." — handled by the caller, which
        # re-runs decide() with damaged_item and adds this sentence as a citation.
        raise ValueError("damaged return must be routed to damaged_item")
    if category == "other" or policy is None:
        return human("unsupported_category", "Route to an agent: request is outside the supported policies.")
    if category == "returns":
        return _returns(policy, rules, facts)
    if category == "damaged_item":
        return _damaged(policy, rules, facts)
    if category == "shipping":
        return _shipping(policy, rules, facts)
    return human("unsupported_category", "Route to an agent: unknown category.")


def _returns(policy: Policy, rules: RetailerRules, f: ResolvedFacts) -> Outcome:
    window = rules.return_window_days
    dsd, final_sale, unused = f.get("days_since_delivery"), f.get("final_sale"), f.get("unused")

    if f.delivered is False:
        return human(
            "return_not_delivered",
            "Route to an agent: return requested but the ERP shows the order as not yet delivered.",
            [excerpt(policy, 0)],
            ["days_overdue"],
        )
    # Decisive negatives first: any one of these settles the case even if others are unknown.
    if final_sale is True:
        return Outcome(
            "policy_supported", "return_final_sale",
            "Decline the return: the item is final sale.",
            "Thanks for reaching out. This item was sold as final sale, and final-sale items "
            "cannot be returned.",
            [excerpt(policy, 1)], [], ["final_sale"],
        )
    if dsd is not None and dsd > window:
        return Outcome(
            "policy_supported", "return_window_passed",
            f"Decline the return: delivered {dsd} days ago, outside the {window}-day window.",
            f"Thanks for reaching out. Unused items can be returned within {window} days of "
            f"delivery, and your order was delivered {dsd} days ago, so it is no longer "
            "eligible for return.",
            [excerpt(policy, 0)], [], ["days_since_delivery"],
        )
    if unused is False:
        return Outcome(
            "policy_supported", "return_item_used",
            "Decline the return: only unused items are returnable.",
            "Thanks for reaching out. Our return policy covers unused items only, so we are "
            "unable to accept a return for an item that has been used.",
            [excerpt(policy, 0)], [], ["unused"],
        )
    checked = (("days_since_delivery", dsd), ("final_sale", final_sale), ("unused", unused))
    missing = [n for n, v in checked if v is None]
    if missing:
        known = [n for n, v in checked if v is not None]
        return needs_info("return_missing_facts", missing, [excerpt(policy, 0), excerpt(policy, 1)], known)
    return Outcome(
        "policy_supported", "return_eligible",
        "Confirm return eligibility and send a prepaid return label. No refund has been executed.",
        f"Thanks for getting in touch. Your unused item was delivered {dsd} days ago, which is "
        f"within our {window}-day return window, so it is eligible for return. We will send "
        "you return instructions shortly.",
        [excerpt(policy, 0)], [], ["days_since_delivery", "final_sale", "unused"],
    )


def _damaged(policy: Policy, rules: RetailerRules, f: ResolvedFacts) -> Outcome:
    if rules.damage_photo_window_days is None:
        return human(
            "damage_always_human",
            "Route to an agent for damaged-item review. Do not promise a refund or replacement.",
            [excerpt(policy, 0), excerpt(policy, 1)],
        )
    window = rules.damage_photo_window_days
    dsd = f.get("days_since_delivery")
    if f.delivered is False:
        return human(
            "damage_not_delivered",
            "Route to an agent: damage reported but the ERP shows the order as not delivered.",
            [], ["days_overdue"],
        )
    if dsd is None:
        return needs_info("damage_missing_delivery", ["days_since_delivery"], [excerpt(policy, 0)], [])
    if dsd > window:
        return human(
            "damage_reported_late",
            f"Route to an agent: damage reported {dsd} days after delivery (> {window}).",
            [excerpt(policy, 1)], ["days_since_delivery"],
        )
    if f.get("photo_provided") is True:
        return Outcome(
            "policy_supported", "damage_photo_received",
            "Agent to review the photo and decide whether to approve a replacement. Nothing approved yet.",
            "Thanks for sending a photo of the damage. Your report is within our damage-reporting "
            "window, and a team member will review it for a possible replacement.",
            [excerpt(policy, 0)], [], ["days_since_delivery", "photo_provided"],
        )
    return Outcome(
        "needs_information", "damage_photo_required",
        "Ask the customer for a photo of the damage before any replacement can be approved.",
        "Sorry to hear your item arrived damaged. Please reply with a photo of the damage so "
        "we can review it for a replacement.",
        [excerpt(policy, 0)], ["photo_provided"], ["days_since_delivery"],
    )


def _shipping(policy: Policy, rules: RetailerRules, f: ResolvedFacts) -> Outcome:
    threshold = rules.ship_investigation_min_overdue
    if f.delivered is True:
        return human(
            "shipping_but_delivered",
            "Route to an agent: customer reports a missing/late shipment but the ERP shows it delivered.",
            [], ["days_since_delivery"],
        )
    od = f.get("days_overdue")
    if od is None:
        return needs_info("shipping_missing_promised_date", ["days_overdue"], [excerpt(policy, 0)], [])
    if od >= threshold:
        return Outcome(
            "policy_supported", "shipping_investigation",
            "Open a carrier investigation. Do not promise or issue a refund.",
            f"Sorry your order is late. It is now {od} days past the promised delivery date, so "
            "we are opening a carrier investigation; this does not automatically mean a refund.",
            [excerpt(policy, 0), excerpt(policy, 1)], [], ["days_overdue"],
        )
    return Outcome(
        "policy_supported", "shipping_not_yet_eligible",
        f"No investigation yet: {od} days overdue, investigation starts at {threshold}.",
        f"Thanks for your patience. Your order is {od} days past its promised delivery date, "
        f"and we open a carrier investigation once a shipment is {threshold} or more days late.",
        [excerpt(policy, 0)], [], ["days_overdue"],
    )
