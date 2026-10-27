from dataclasses import dataclass, field

# Numbers live in code (enforced outside the prompt); the *evidence text* comes from the DB.
RETURN_DAYS = {"northstar": 30, "cedar": 14}   # eligible while days_since_delivery <= N
PHOTO_DAYS = {"northstar": 7}                   # photo needed while days_since_delivery <= N
SHIP_DAYS = {"northstar": 6, "cedar": 4}        # investigate when days_overdue >= N

HANDOFF = "A member of our team will review your request and follow up with you."


@dataclass
class Outcome:
    decision: str
    next_action: str
    reply: str                                   # deterministic safe wording (also the model's brief)
    cite: list = field(default_factory=list)     # sentence indexes inside the category policy
    missing: list = field(default_factory=list)


def review(next_action: str, cite=None) -> Outcome:
    return Outcome("human_review", next_action, f"Thanks for getting in touch. {HANDOFF}", cite or [])


def decide(category: str, retailer: str, f: dict, erp_damaged: bool = False) -> Outcome:
    if category == "returns":
        return _returns(retailer, f, erp_damaged)
    if category == "damaged_item":
        return _damaged(retailer, f)
    if category == "shipping":
        return _shipping(retailer, f)
    return review("Route to a human agent: request is outside the supported policies.")


def _returns(r: str, f: dict, erp_damaged: bool) -> Outcome:
    window = RETURN_DAYS[r]
    if erp_damaged:  # sentence 2: "Damaged items follow the damaged-item policy."
        return review("Order is recorded as damaged: handle under the damaged-item policy via human review.", [2])
    if f.get("final_sale") is True:
        return Outcome("policy_supported", "Decline the return: final-sale items cannot be returned.",
                       "This item was sold as final sale, so unfortunately it can't be returned.", [1])
    days = f.get("days_since_delivery")
    if days is not None and days > window:
        return Outcome("policy_supported", f"Decline the return: the {window}-day window has passed. Offer no exception.",
                       f"Our return window is {window} days from delivery and it has passed, so we can't accept this return.", [0])
    if f.get("unused") is False:
        return Outcome("policy_supported", "Decline the return: only unused items may be returned.",
                       "Only unused items can be returned, so we can't accept this return.", [0])
    missing = [k for k in ("days_since_delivery", "unused", "final_sale") if f.get(k) is None]
    if missing:
        return Outcome("needs_information", "Ask the customer for the missing order details.",
                       "To check your return we need a few more details about your order. Could you confirm them for us?", [0], missing)
    return Outcome("policy_supported", "Return is within policy: confirm eligibility and send return instructions.",
                   "Based on our policy, your item appears eligible for return. A team member will confirm the next steps.", [0])


def _damaged(r: str, f: dict) -> Outcome:
    if r == "cedar":  # C-DMG: always human review, promise nothing
        return review("Human review required for all damaged-item complaints. Promise no refund or replacement.", [0, 1])
    days = f.get("days_since_delivery")
    if days is None:
        return Outcome("needs_information", "Ask for the delivery date of the item.",
                       "To look into the damage we need to confirm when your order was delivered. Could you share that with us?", [0], ["days_since_delivery"])
    if days > PHOTO_DAYS[r]:
        return review("Damage reported after the 7-day window: human review required.", [1])
    if f.get("photo_provided") is True:
        return Outcome("policy_supported", "Photo received: proceed to replacement approval review (nothing approved yet).",
                       "Thanks for the photo. Our team will review it and let you know the outcome.", [0])
    return Outcome("needs_information", "Request a photo of the damage. Do not promise an approved replacement.",
                   "We're sorry your item arrived damaged. Please send us a photo of the damage so we can review your request.", [0], ["photo_provided"])


def _shipping(r: str, f: dict) -> Outcome:
    if f.get("days_since_delivery") is not None:
        return review("Order is already delivered: shipping policy does not apply, human review.")
    overdue = f.get("days_overdue")
    if overdue is None:
        return Outcome("needs_information", "Ask for the promised delivery date.",
                       "To check on your shipment we need its promised delivery date. Could you share it with us?", [0], ["days_overdue"])
    threshold = SHIP_DAYS[r]
    if overdue >= threshold:
        return Outcome("policy_supported", "Open a carrier investigation. Do not promise a refund.",
                       "Your shipment is past its promised delivery date, so we're opening a carrier investigation.", [0, 1])
    return Outcome("policy_supported", f"Not yet eligible for a carrier investigation (needs {threshold}+ days overdue).",
                   "Your shipment isn't yet far enough past its promised date for a carrier investigation. Please check back soon.", [0])