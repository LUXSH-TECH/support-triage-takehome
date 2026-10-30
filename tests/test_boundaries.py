from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.decisions import decide
from app.repositories.policy_repository import Policy


POLICIES = json.loads((Path(__file__).resolve().parents[1] / "data" / "policies.json").read_text())


def policy_for(retailer: str, category: str) -> Policy:
    item = next(
        value
        for value in POLICIES
        if value["retailer"] == retailer and value["category"] == category
    )
    return Policy(item["policy_id"], retailer, category, item["text"])


@pytest.mark.parametrize(
    ("retailer", "day", "expected"),
    [
        ("northstar", 30, "eligible"),
        ("northstar", 31, "outside"),
        ("cedar", 14, "eligible"),
        ("cedar", 15, "outside"),
    ],
)
def test_return_window_boundaries(retailer: str, day: int, expected: str) -> None:
    outcome = decide(
        retailer,
        "returns",
        {"days_since_delivery": day, "unused": True, "final_sale": False},
        policy_for(retailer, "returns"),
    )
    assert outcome.decision == "policy_supported"
    if expected == "eligible":
        assert "meet the return policy" in outcome.next_action
    else:
        assert "outside the" in outcome.next_action


@pytest.mark.parametrize("day", [0, 8, 31, 365])
def test_final_sale_is_never_returnable(day: int) -> None:
    outcome = decide(
        "northstar",
        "returns",
        {"days_since_delivery": day, "unused": True, "final_sale": True},
        policy_for("northstar", "returns"),
    )
    assert outcome.decision == "policy_supported"
    assert "not eligible" in outcome.next_action
    assert outcome.citation_sentence_index == 1


@pytest.mark.parametrize(("day", "expected"), [(7, "photo"), (8, "human")])
def test_northstar_damage_photo_boundary(day: int, expected: str) -> None:
    outcome = decide(
        "northstar",
        "damaged_item",
        {"days_since_delivery": day, "photo_provided": False},
        policy_for("northstar", "damaged_item"),
    )
    if expected == "photo":
        assert outcome.decision == "needs_information"
        assert "photo" in outcome.next_action
    else:
        assert outcome.decision == "human_review"


@pytest.mark.parametrize(
    ("retailer", "days", "expected"),
    [
        ("northstar", 5, False),
        ("northstar", 6, True),
        ("cedar", 3, False),
        ("cedar", 4, True),
    ],
)
def test_shipping_investigation_boundaries(retailer: str, days: int, expected: bool) -> None:
    outcome = decide(
        retailer,
        "shipping",
        {"days_overdue": days},
        policy_for(retailer, "shipping"),
    )
    assert outcome.decision == "policy_supported"
    assert ("eligible" in outcome.next_action) is expected


def test_cedar_damage_always_requires_human_review() -> None:
    outcome = decide(
        "cedar",
        "damaged_item",
        {"days_since_delivery": 1, "photo_provided": True},
        policy_for("cedar", "damaged_item"),
    )
    assert outcome.decision == "human_review"
    assert "no refund or replacement" in outcome.next_action