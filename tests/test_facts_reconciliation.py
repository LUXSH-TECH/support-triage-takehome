"""Client-vs-ERP reconciliation and fact derivation (unit level) + API routing."""

from datetime import date

from app.services.erp_service import ErpOrder
from app.services.facts_service import resolve_facts
from app.schemas import ClientFacts

from .conftest import memory_erp, order, triage

TODAY = date(2025, 9, 1)


def erp(**kw):
    base = dict(order_ref="NS-1", retailer="northstar", order_date=None, delivery_date=date(2025, 8, 12),
                promised_date=date(2025, 8, 10), final_sale=False, item_condition="UNUSED", channel="web")
    base.update(kw)
    return ErpOrder(**base)


def test_derives_days_from_erp_and_ignores_client_days():
    f = resolve_facts(erp(), ClientFacts(days_since_delivery=21), TODAY)
    assert f.values["days_since_delivery"] == 20 and f.sources["days_since_delivery"] == "erp"
    assert f.values["days_overdue"] == 0  # delivered => not overdue
    assert f.discrepancies == []  # within the 1-day tolerance


def test_day_count_contradiction_beyond_tolerance():
    f = resolve_facts(erp(), ClientFacts(days_since_delivery=5), TODAY)
    assert f.discrepancies == ["days_since_delivery: client=5, erp=20"]


def test_final_sale_and_unused_contradictions():
    f = resolve_facts(erp(final_sale=True, item_condition="USED"), ClientFacts(final_sale=False, unused=True), TODAY)
    assert "final_sale: client=false, erp=true" in f.discrepancies
    assert "unused: client=true, erp=USED" in f.discrepancies


def test_client_claims_overdue_but_erp_delivered():
    f = resolve_facts(erp(), ClientFacts(days_overdue=7), TODAY)
    assert f.discrepancies == ["days_overdue: client=7, erp=delivered"]


def test_client_claims_delivery_but_erp_not_delivered():
    f = resolve_facts(erp(delivery_date=None, promised_date=date(2025, 8, 26)), ClientFacts(days_since_delivery=3), TODAY)
    assert f.delivered is False
    assert f.values["days_overdue"] == 6
    assert "days_since_delivery" not in f.values
    assert f.discrepancies == ["days_since_delivery: client=3, erp=not_delivered"]


def test_blank_erp_condition_falls_back_to_client_hint_labelled_client():
    f = resolve_facts(erp(item_condition=None), ClientFacts(unused=True), TODAY)
    assert f.values["unused"] is True and f.sources["unused"] == "client"


def test_blank_erp_final_sale_is_not_filled_by_client():
    f = resolve_facts(erp(final_sale=None), ClientFacts(final_sale=False), TODAY)
    assert "final_sale" not in f.values
    assert "final_sale" in f.incomplete_fields


def test_no_erp_record_means_no_order_facts():
    f = resolve_facts(None, ClientFacts(days_since_delivery=3, unused=True, final_sale=False, photo_provided=True), TODAY)
    assert set(f.values) == {"photo_provided"}


def test_future_delivery_date_is_treated_as_incomplete():
    f = resolve_facts(erp(delivery_date=date(2025, 9, 5)), ClientFacts(), TODAY)
    assert "days_since_delivery" not in f.values and "delivery_date" in f.incomplete_fields


# ---- API-level routing --------------------------------------------------------------

def test_api_day_contradiction_routes_to_human_review(client):
    r = triage(client, "northstar", "I'd like to return this jacket.", "NS-88231", {"days_since_delivery": 2}).json()
    assert r["decision"] == "human_review"
    assert r["discrepancies"] == ["days_since_delivery: client=2, erp=20"]
    assert r["fact_sources"]["days_since_delivery"] == "erp"


def test_api_incomplete_erp_record_routes_to_agent_not_customer(make_client):
    # ERP lacks final_sale (an ERP-only fact): the client hint cannot fill it, so asking the
    # customer would loop forever. Route to an agent and list what is missing.
    o = order("NS-INC", "northstar", delivered_days_ago=5, final_sale=None, condition=None)
    c = make_client(erp=memory_erp(o))
    r = triage(c, "northstar", "I'd like to return this.", "NS-INC", {"final_sale": False}).json()
    assert r["decision"] == "human_review"
    assert r["missing_information"] == ["final_sale", "unused"]
    assert "ERP record is missing final_sale" in r["next_action"]
    assert r["fact_sources"] == {"days_since_delivery": "erp"}


def test_api_missing_customer_suppliable_fact_asks_customer(make_client):
    # ERP has every ERP-only fact but no condition: ask the customer whether it is unused.
    o = order("NS-U", "northstar", delivered_days_ago=5, condition=None)
    c = make_client(erp=memory_erp(o))
    r = triage(c, "northstar", "I'd like to return this.", "NS-U").json()
    assert r["decision"] == "needs_information"
    assert r["missing_information"] == ["unused"]
    assert r["fact_sources"] == {"days_since_delivery": "erp", "final_sale": "erp"}
    # ...and once the customer answers, the hint is used (labelled client).
    r2 = triage(c, "northstar", "I'd like to return this.", "NS-U", {"unused": True}).json()
    assert r2["decision"] == "policy_supported" and r2["fact_sources"]["unused"] == "client"


def test_damaged_erp_item_with_client_unused_is_not_a_discrepancy():
    f = resolve_facts(erp(item_condition="DAMAGED"), ClientFacts(unused=True), TODAY)
    assert f.damaged_in_erp and f.discrepancies == []


def test_api_fixture_record_without_any_dates_is_incomplete(client):
    # NS-88270: no delivery date and no promised date: delivery status is unknown.
    r = triage(client, "northstar", "I want to return this.", "NS-88270").json()
    assert r["decision"] == "human_review"
    assert "not yet delivered" not in r["next_action"]
    assert "days_since_delivery" in r["missing_information"]


def test_api_fixture_incomplete_shipping_record(client):
    # NS-88270: no delivery date and no promised date in the legacy feed.
    r = triage(client, "northstar", "Where is my order? It hasn't arrived.", "NS-88270").json()
    assert r["decision"] == "human_review"
    assert r["missing_information"] == ["days_overdue"]
