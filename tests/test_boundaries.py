"""Exact day-count boundaries (delivery day is day zero), end-to-end through the API with
synthetic ERP records derived from the fixed reference date 2025-09-01."""

import pytest

from .conftest import memory_erp, order, triage


@pytest.mark.parametrize(
    "retailer,prefix,days,expected",
    [
        ("northstar", "NS", 0, "eligible"),
        ("northstar", "NS", 30, "eligible"),
        ("northstar", "NS", 31, "window"),
        ("cedar", "CD", 14, "eligible"),
        ("cedar", "CD", 15, "window"),
    ],
)
def test_return_window(make_client, retailer, prefix, days, expected):
    ref = f"{prefix}-B{days}"
    c = make_client(erp=memory_erp(order(ref, retailer, delivered_days_ago=days)))
    r = triage(c, retailer, "I want to return this.", ref).json()
    assert r["decision"] == "policy_supported"
    if expected == "eligible":
        assert "eligible for return" in r["customer_response"] and "no longer" not in r["customer_response"]
    else:
        assert "no longer eligible" in r["customer_response"]


@pytest.mark.parametrize("days", [0, 5, 30])
def test_final_sale_never_returnable(make_client, days):
    c = make_client(erp=memory_erp(order("NS-FS", "northstar", delivered_days_ago=days, final_sale=True)))
    r = triage(c, "northstar", "I want to return this.", "NS-FS").json()
    assert r["decision"] == "policy_supported"
    assert r["citations"] == [{"policy_id": "N-RET", "excerpt": "Final-sale items cannot be returned."}]
    assert "cannot be returned" in r["customer_response"]


@pytest.mark.parametrize("days,photo,decision", [
    (7, False, "needs_information"),
    (7, True, "policy_supported"),
    (8, False, "human_review"),
    (8, True, "human_review"),
])
def test_northstar_damage_photo_window(make_client, days, photo, decision):
    c = make_client(erp=memory_erp(order("NS-D", "northstar", delivered_days_ago=days, condition="DAMAGED")))
    r = triage(c, "northstar", "It arrived broken.", "NS-D", {"photo_provided": photo}).json()
    assert r["category"] == "damaged_item"
    assert r["decision"] == decision
    if decision == "policy_supported":
        # Photo received: a replacement may be *considered*, never declared approved.
        assert "approved" not in r["customer_response"].lower()


@pytest.mark.parametrize("days", [0, 3, 30])
def test_cedar_damage_always_human_review(make_client, days):
    c = make_client(erp=memory_erp(order("CD-D", "cedar", delivered_days_ago=days, condition="DAMAGED")))
    r = triage(c, "cedar", "It arrived broken.", "CD-D", {"photo_provided": True}).json()
    assert r["decision"] == "human_review"
    assert {c["policy_id"] for c in r["citations"]} == {"C-DMG"}


@pytest.mark.parametrize("retailer,prefix,overdue,investigate", [
    ("northstar", "NS", 5, False),
    ("northstar", "NS", 6, True),
    ("cedar", "CD", 3, False),
    ("cedar", "CD", 4, True),
])
def test_shipping_investigation_threshold(make_client, retailer, prefix, overdue, investigate):
    ref = f"{prefix}-S{overdue}"
    c = make_client(erp=memory_erp(order(ref, retailer, overdue_days=overdue)))
    r = triage(c, retailer, "Where is my order? It hasn't arrived.", ref).json()
    assert r["decision"] == "policy_supported"
    assert ("opening a carrier investigation" in r["customer_response"]) is investigate


def test_delivered_late_order_does_not_trigger_shipping_policy(make_client):
    # Delivered 2 days ago, 10 days after the promised date: history, not an open case.
    o = order("NS-LATE", "northstar", delivered_days_ago=2, overdue_days=12)
    c = make_client(erp=memory_erp(o))
    r = triage(c, "northstar", "My order was late!", "NS-LATE").json()
    assert r["decision"] == "human_review"
    assert "investigation" not in r["customer_response"]
