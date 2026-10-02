"""Exact day-count edges, driven through the API with a generated ERP feed."""
import pytest

from tests.conftest import CD, NS, ago, post

RET = "I'd like to return this, it doesn't fit."
DMG = "My item arrived damaged."
SHIP = "Where is my order? It is late."


@pytest.mark.parametrize("headers,window", [(NS, 30), (CD, 14)])
@pytest.mark.parametrize("delta,eligible", [(0, True), (-1, True), (1, False)])
def test_return_window_edges(psv_client, headers, window, delta, eligible):
    days = window + delta
    retailer = "NORTHSTAR" if headers is NS else "CEDAR"
    c = psv_client([f"X-1|{retailer}|01-01-2025|{ago(days)}|{ago(days + 1)}|N|UNUSED|web"])
    r = post(c, headers, RET, "X-1").json()
    assert r["decision"] == "policy_supported"
    assert ("within policy" in r["next_action"]) is eligible
    assert ("has passed" in r["next_action"]) is (not eligible)


@pytest.mark.parametrize("days", [0, 100])
def test_final_sale_never_returnable(psv_client, days):
    c = psv_client([f"X-1|NORTHSTAR|01-01-2025|{ago(days)}|{ago(days + 1)}|Y|UNUSED|web"])
    r = post(c, NS, RET, "X-1").json()
    assert r["decision"] == "policy_supported" and "final-sale" in r["next_action"]


@pytest.mark.parametrize("days,decision", [(7, "needs_information"), (8, "human_review")])
def test_northstar_photo_window_edges(psv_client, days, decision):
    c = psv_client([f"X-1|NORTHSTAR|01-01-2025|{ago(days)}|{ago(days + 1)}|N|DAMAGED|web"])
    r = post(c, NS, DMG, "X-1").json()
    assert r["decision"] == decision
    if decision == "needs_information":
        assert r["missing_information"] == ["photo_provided"]


def test_northstar_damage_with_photo_within_window(psv_client):
    c = psv_client([f"X-1|NORTHSTAR|01-01-2025|{ago(3)}|{ago(4)}|N|DAMAGED|web"])
    r = post(c, NS, DMG, "X-1", {"photo_provided": True}).json()
    assert r["decision"] == "policy_supported" and r["fact_sources"]["photo_provided"] == "client"


@pytest.mark.parametrize("headers,retailer,threshold", [(NS, "NORTHSTAR", 6), (CD, "CEDAR", 4)])
@pytest.mark.parametrize("delta,investigate", [(-1, False), (0, True)])
def test_shipping_edges(psv_client, headers, retailer, threshold, delta, investigate):
    overdue = threshold + delta
    c = psv_client([f"X-1|{retailer}|01-01-2025||{ago(overdue)}|N||web"])
    r = post(c, headers, SHIP, "X-1").json()
    assert r["decision"] == "policy_supported"
    assert ("carrier investigation" in r["next_action"] and "Not yet" not in r["next_action"]) is investigate


def test_delivered_late_shipment_does_not_trigger_shipping_policy(psv_client):
    c = psv_client([f"X-1|NORTHSTAR|01-01-2025|{ago(2)}|{ago(20)}|N|UNUSED|web"])
    r = post(c, NS, SHIP, "X-1").json()
    assert r["decision"] == "human_review" and r["citations"] == []