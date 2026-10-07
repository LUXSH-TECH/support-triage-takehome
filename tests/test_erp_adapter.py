"""Legacy ERP adapter: parsing, isolation, simulated failures."""

import json
from datetime import date
from pathlib import Path

import pytest

from app.erp import ErpError, ErpTimeout, FlatFileErpAdapter

from .conftest import triage

FEED = Path(__file__).parent.parent / "erp" / "orders.psv"


@pytest.fixture
def adapter():
    return FlatFileErpAdapter(FEED, slow_delay_s=0.01)


def test_parses_dd_mm_yyyy_and_flags(adapter):
    o = adapter.get_order("NS-88231", "northstar")
    assert o.delivery_date == date(2025, 8, 12) and o.promised_date == date(2025, 8, 10)
    assert o.final_sale is False and o.item_condition == "UNUSED" and o.retailer == "northstar"


def test_blank_fields_are_none_not_invented(adapter):
    o = adapter.get_order("NS-88270", "northstar")
    assert o.delivery_date is None and o.promised_date is None and o.item_condition is None


def test_cross_retailer_lookup_is_not_found(adapter):
    assert adapter.get_order("NS-88231", "cedar") is None
    assert adapter.get_order("CD-40012", "northstar") is None


def test_timeout_convention(adapter):
    with pytest.raises(ErpTimeout):
        adapter.get_order("NS-88231-TIMEOUT", "northstar")


def test_slow_convention_returns_base_record(adapter):
    assert adapter.get_order("NS-88231-SLOW", "northstar").order_ref == "NS-88231"


def test_missing_feed_raises_erp_error(tmp_path):
    with pytest.raises(ErpError):
        FlatFileErpAdapter(tmp_path / "nope.psv").get_order("NS-88231", "northstar")


def test_api_slow_but_within_timeout_succeeds(client):
    r = triage(client, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231-SLOW").json()
    assert r["decision"] == "policy_supported" and r["model"]["fallback"] is False


def test_api_slow_beyond_service_timeout_falls_back(make_client):
    c = make_client(erp_slow_delay_s=0.5, erp_timeout_s=0.1)
    r = triage(c, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231-SLOW").json()
    assert r["decision"] == "human_review" and r["model"]["fallback"] is True
    assert "erp_timeout" in r["next_action"]


def test_api_erp_unavailable_falls_back(make_client, tmp_path):
    c = make_client(erp_feed=tmp_path / "missing.psv")
    r = triage(c, "northstar", "I want to return this.", "NS-88231").json()
    assert r["decision"] == "human_review" and "erp_error" in r["next_action"]
    assert r["citations"] == []


def test_api_cedar_damaged_fixture(client):
    r = triage(client, "cedar", "The vase arrived cracked.", "CD-40045", {"photo_provided": True}).json()
    assert r["decision"] == "human_review"
    assert "replacement" not in r["customer_response"].lower() and "refund" not in r["customer_response"].lower()


def test_api_return_request_on_damaged_item_follows_damaged_policy(client):
    r = triage(client, "northstar", "I want to return this.", "NS-88240").json()
    assert r["category"] == "damaged_item"
    assert r["citations"][0] == {"policy_id": "N-RET", "excerpt": "Damaged items follow the damaged-item policy."}
    assert r["citations"][1]["policy_id"] == "N-DMG"
    assert r["decision"] == "needs_information"
    json.dumps(r)
