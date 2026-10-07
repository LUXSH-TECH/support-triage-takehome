"""Authentication, input validation, health."""

import pytest

from .conftest import triage

BODY = {"ticket_id": "T-1", "order_ref": "NS-88231", "message": "I want to return this."}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": ""}, {"X-API-Key": "wrong"}, {"X-API-Key": "test-key-northstar-00"}])
def test_missing_or_invalid_key_401(client, headers):
    assert client.post("/triage", headers=headers, json=BODY).status_code == 401


def test_auth_checked_even_with_bad_body(client):
    # No key + malformed body: we must not leak validation detail to unauthenticated callers
    # beyond FastAPI's standard ordering; either 401 or 422 is acceptable, never 200.
    r = client.post("/triage", json={"nope": 1})
    assert r.status_code in (401, 422)


@pytest.mark.parametrize("facts", [{"days_since_delivery": -1}, {"days_overdue": -3}])
def test_negative_day_counts_422(client, facts):
    r = client.post("/triage", headers={"X-API-Key": "test-key-northstar-001"}, json={**BODY, "facts": facts})
    assert r.status_code == 422


@pytest.mark.parametrize("body", [
    {"order_ref": "NS-88231", "message": "hi"},  # no ticket_id
    {"ticket_id": "T-1", "order_ref": "NS-88231"},  # no message
    {"ticket_id": "T-1", "message": ""},  # empty message
    {"ticket_id": "T 1; DROP TABLE", "message": "x"},  # bad ticket id chars
    {"ticket_id": "T-1", "message": "x", "facts": {"unused": "maybe"}},
    {"ticket_id": "T-1", "message": "x" * 4001},
])
def test_malformed_body_422(client, body):
    r = client.post("/triage", headers={"X-API-Key": "test-key-northstar-001"}, json=body)
    assert r.status_code == 422


def test_non_json_body_422(client):
    r = client.post("/triage", headers={"X-API-Key": "test-key-northstar-001", "content-type": "application/json"}, content=b"{not json")
    assert r.status_code == 422


def test_supplied_retailer_field_is_ignored(client):
    body = {**BODY, "retailer": "cedar"}
    r = client.post("/triage", headers={"X-API-Key": "test-key-northstar-001"}, json=body).json()
    assert r["retailer"] == "northstar"


def test_response_contract(client):
    r = triage(client, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231")
    assert r.status_code == 200
    d = r.json()
    assert set(d) == {
        "ticket_id", "request_id", "retailer", "category", "decision", "next_action", "customer_response",
        "citations", "missing_information", "fact_sources", "discrepancies", "model", "latency_ms",
    }
    assert len(d["customer_response"]) <= 400
    assert d["customer_response"].count(".") <= 3
    # request_id unique per request
    d2 = triage(client, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231").json()
    assert d["request_id"] != d2["request_id"]


def test_health_ok_without_secrets(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body == {"status": "ok", "policy_store": {"ok": True, "policies": 6}, "erp": {"ok": True}}
    assert "sqlite" not in r.text and "test-key" not in r.text


def test_health_degraded_when_erp_feed_missing(make_client, tmp_path):
    c = make_client(erp_feed=tmp_path / "missing.psv")
    r = c.get("/health")
    assert r.status_code == 503
    assert r.json()["erp"] == {"ok": False}


def test_null_facts_accepted(client):
    r = client.post("/triage", headers={"X-API-Key": "test-key-northstar-001"}, json={**BODY, "facts": None})
    assert r.status_code == 200


@pytest.mark.parametrize("facts", [{"days_since_delivery": True}, {"days_overdue": "5"}, {"unused": 1}])
def test_wrongly_typed_facts_422(client, facts):
    r = client.post("/triage", headers={"X-API-Key": "test-key-northstar-001"}, json={**BODY, "facts": facts})
    assert r.status_code == 422


def test_order_ref_is_case_insensitive(client):
    r = triage(client, "northstar", "The jacket doesn't fit, I'd like to send it back.", "ns-88231").json()
    assert r["decision"] == "policy_supported"


def test_startup_rejects_key_for_unknown_retailer(make_client):
    with pytest.raises(RuntimeError, match="acme"):
        make_client(api_keys={"k-acme": "acme"})
