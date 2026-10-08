"""Policy-rule/text consistency, classifier sanity, and the output guardrail detector."""

import json
import re
from pathlib import Path

import pytest

from app.services.classifier_service import classify
from app.services.guardrail_service import validate_draft
from app.services.policy_service import RULES, sentences

POLICIES = {p["policy_id"]: p for p in json.loads((Path(__file__).parent.parent / "data" / "policies.json").read_text())}
WORDS = {"three": 3, "five": 5, "seven": 7}


def number_in(text: str, phrase_rx: str) -> int:
    m = re.search(phrase_rx, text)
    assert m, (phrase_rx, text)
    v = m.group(1)
    return int(v) if v.isdigit() else WORDS[v]


@pytest.mark.parametrize("retailer,prefix", [("northstar", "N"), ("cedar", "C")])
def test_rule_thresholds_match_policy_text(retailer, prefix):
    """If someone edits a policy's wording without updating RULES (or vice versa), fail."""
    r = RULES[retailer]
    assert number_in(POLICIES[f"{prefix}-RET"]["text"], r"within (\w+) days") == r.return_window_days
    # "more than N days" => investigation from N+1
    assert number_in(POLICIES[f"{prefix}-SHIP"]["text"], r"more than (\w+) days") + 1 == r.ship_investigation_min_overdue
    if r.damage_photo_window_days is not None:
        assert number_in(POLICIES[f"{prefix}-DMG"]["text"], r"within (\w+) days") == r.damage_photo_window_days
    else:
        assert "All damaged-item complaints require human review" in POLICIES[f"{prefix}-DMG"]["text"]


def test_sentence_split_is_verbatim():
    for p in POLICIES.values():
        for s in sentences(p["text"]):
            assert s in p["text"]


@pytest.mark.parametrize("msg,cat,mixed,unsupported", [
    ("This doesn't fit, can I send it back?", "returns", False, False),
    ("The mug arrived cracked", "damaged_item", False, False),
    ("My parcel still hasn't arrived", "shipping", False, False),
    ("It came broken and I want to return it", "damaged_item", False, False),
    ("It arrived late and the box was smashed", "damaged_item", True, False),
    ("Is this covered by warranty?", "other", False, True),
    ("Hello, I have a question about my order", "other", False, False),
    ("My item is not damaged, I just want to return it", "returns", False, False),
    ("I'd like to return it, I still have the receipt", "returns", False, False),
    ("Sorry for the late reply, I want to return it", "returns", False, False),
    ("Please send me a VAT invoice", "other", False, True),
    ("The kettle broke, is it under warranty?", "other", False, True),
])
def test_classifier_examples(msg, cat, mixed, unsupported):
    c = classify(msg)
    assert (c.category, c.mixed, c.unsupported) == (cat, mixed, unsupported)


def test_mixed_issue_routes_to_human_review(client):
    from .conftest import triage
    r = triage(client, "northstar", "My order arrived two weeks late and the screen is cracked.", "NS-88240").json()
    assert r["decision"] == "human_review"


KW = dict(
    retailer="cedar",
    other_retailer_policy_ids=["N-RET", "N-DMG", "N-SHIP"],
    other_retailer_texts=[POLICIES[p]["text"] for p in ("N-RET", "N-DMG", "N-SHIP")],
    own_texts=[POLICIES[p]["text"] for p in ("C-RET", "C-DMG", "C-SHIP")],
    allowed_numbers={14, 20, 4, 3},
)


@pytest.mark.parametrize("draft,violation", [
    ("Your refund has been approved.", "unsupported_promise"),
    ("We will refund you today.", "unsupported_promise"),
    ("Your replacement is on its way.", "unsupported_promise"),
    ("You will receive a full refund.", "unsupported_promise"),
    ("Your refund is on the way.", "unsupported_promise"),
    ("A replacement is being shipped to you.", "unsupported_promise"),
    ("Refund approved.", "unsupported_promise"),
    ("We'd be happy to refund you in full.", "unsupported_promise"),
    ("We will extend the window for you this time.", "unsupported_promise"),
    ("We can offer you store credit instead.", "unsupported_promise"),
    ("As an exception, you can return it.", "unsupported_promise"),
    ("Northstar would let you return this.", "cross_retailer_name"),
    ("Per N-RET you may return within 30 days.", "cross_retailer_policy_id"),
    ("Items may be returned within 30 days of delivery.", "cross_retailer_policy_text"),
    ("Your order was delivered 45 days ago.", "ungrounded_number:45"),
    ("A. B. C. D.", "too_many_sentences"),
    ("x" * 401, "too_long"),
    ("", "empty"),
])
def test_guardrail_flags_bad_drafts(draft, violation):
    assert violation in validate_draft(draft, **KW)


def test_guardrail_accepts_grounded_draft():
    ok = ("Thanks for reaching out. Unused items can be returned within 14 days of delivery, and your order "
          "was delivered 20 days ago, so it is no longer eligible for return.")
    assert validate_draft(ok, **KW) == []
