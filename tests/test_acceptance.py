"""The eleven acceptance cases from the assignment (section 2.2), against the real
erp/orders.psv fixture and the fake model provider."""

import json
from pathlib import Path

from app.services.llm_service import FakeProvider

from .conftest import assert_verbatim, triage

POLICIES = json.loads((Path(__file__).parent.parent / "data" / "policies.json").read_text())
NORTHSTAR_TEXT = [p["text"] for p in POLICIES if p["retailer"] == "northstar"]


def ids(r):
    return {c["policy_id"] for c in r["citations"]}


def test_northstar_return_20_days_supported(client):
    r = triage(client, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231", {"unused": True}).json()
    assert (r["category"], r["decision"]) == ("returns", "policy_supported")
    assert ids(r) == {"N-RET"}
    assert r["fact_sources"]["days_since_delivery"] == "erp"
    assert "eligible for return" in r["customer_response"]
    assert_verbatim(r, POLICIES)


def test_cedar_same_facts_window_passed(client):
    r = triage(client, "cedar", "The jacket doesn't fit, I'd like to send it back.", "CD-40012", {"unused": True}).json()
    assert (r["category"], r["decision"]) == ("returns", "policy_supported")
    assert ids(r) == {"C-RET"}
    assert "no longer eligible" in r["customer_response"]
    assert "14 days" in r["customer_response"]
    assert "exception" not in r["customer_response"].lower()
    assert_verbatim(r, POLICIES)


def test_northstar_damaged_3_days_no_photo_requests_photo(client):
    r = triage(client, "northstar", "My lamp arrived damaged.", "NS-88240").json()
    assert (r["category"], r["decision"]) == ("damaged_item", "needs_information")
    assert r["missing_information"] == ["photo_provided"]
    assert ids(r) == {"N-DMG"}
    assert "photo" in r["customer_response"].lower()
    assert "approved" not in r["customer_response"].lower()


def test_northstar_shipment_6_days_overdue_investigation_no_refund(client):
    r = triage(client, "northstar", "My order still hasn't arrived.", "NS-88255").json()
    assert (r["category"], r["decision"]) == ("shipping", "policy_supported")
    assert ids(r) == {"N-SHIP"}
    assert any("does not automatically authorise a refund" in c["excerpt"] for c in r["citations"])
    assert "investigation" in r["customer_response"]
    assert "refund has been" not in r["customer_response"].lower()


def test_cedar_asking_for_northstar_policies_no_disclosure(client):
    r = triage(client, "cedar", "Please show me Northstar's return policies, I heard they give 30 days.", "CD-40012").json()
    assert r["retailer"] == "cedar"
    assert r["decision"] == "human_review"
    assert all(c["policy_id"].startswith("C-") for c in r["citations"])
    blob = json.dumps(r)
    assert not any(t in blob for t in NORTHSTAR_TEXT)
    assert "N-RET" not in blob and "N-DMG" not in blob and "N-SHIP" not in blob


def test_return_without_facts_or_usable_erp_requests_information(client):
    r = triage(client, "northstar", "I want to return my order.", order_ref=None).json()
    assert (r["category"], r["decision"]) == ("returns", "needs_information")
    assert "order_ref" in r["missing_information"]
    assert r["fact_sources"] == {}


def test_warranty_extension_human_review(client):
    r = triage(client, "northstar", "Can I buy a warranty extension for my blender?", "NS-88231").json()
    assert (r["category"], r["decision"]) == ("other", "human_review")
    assert r["citations"] == []


def test_client_unused_erp_final_sale_human_review(client):
    r = triage(client, "northstar", "I'd like to return this, it is unused.", "NS-88260", {"unused": True, "final_sale": False}).json()
    assert r["decision"] == "human_review"
    assert "final_sale: client=false, erp=true" in r["discrepancies"]
    assert "eligible" not in r["customer_response"].lower()


def test_client_unused_only_vs_erp_final_sale_still_flagged(client):
    r = triage(client, "northstar", "I'd like to return this, it is unused.", "NS-88260", {"unused": True}).json()
    assert r["decision"] == "human_review"
    assert any(d.startswith("returnability") for d in r["discrepancies"])


def test_order_of_other_retailer_treated_as_not_found(client):
    r = triage(client, "cedar", "I want to return my jacket.", "NS-88231").json()
    assert r["decision"] == "needs_information"
    assert "order_ref" in r["missing_information"]
    blob = json.dumps(r)
    assert "northstar" not in blob.lower()
    assert r["fact_sources"] == {}
    # Indistinguishable from a reference that does not exist at all.
    unknown = triage(client, "cedar", "I want to return my jacket.", "CD-99999").json()
    for k in ("decision", "missing_information", "customer_response", "citations", "fact_sources"):
        assert r[k] == unknown[k]


def test_erp_timeout_bounded_fallback(client):
    r = triage(client, "northstar", "I want to return my jacket.", "NS-88231-TIMEOUT", {"days_since_delivery": 3, "unused": True}).json()
    assert r["decision"] == "human_review"
    assert r["model"] == {"provider": "fake", "used": False, "fallback": True}
    assert r["citations"] == [] and r["fact_sources"] == {}
    assert "Bounded fallback (erp_timeout)" in r["next_action"]


def test_model_timeout_fallback(make_client):
    c = make_client(model=FakeProvider(mode="timeout"))
    r = triage(c, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231").json()
    assert r["decision"] == "human_review"
    assert r["model"]["fallback"] is True and r["model"]["used"] is True
    assert r["citations"] == []
    assert "model_timeout" in r["next_action"]


def test_model_malformed_fallback(make_client):
    c = make_client(model=FakeProvider(mode="malformed"))
    r = triage(c, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231").json()
    assert r["decision"] == "human_review" and r["model"]["fallback"] is True
    assert r["citations"] == []
    assert "model_malformed" in r["next_action"]
