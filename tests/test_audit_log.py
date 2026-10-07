"""One triage_log row per request, including fallbacks; no message text stored."""

import json

from app.llm import FakeProvider

from .conftest import triage


def rows(client):
    return client.app.state.service.audit.all()


def test_row_written_for_success(client):
    r = triage(client, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231", ticket_id="T-42").json()
    row = client.app.state.service.audit.get(r["request_id"])
    assert row["ticket_id"] == "T-42" and row["retailer"] == "northstar"
    assert row["category"] == "returns" and row["decision"] == "policy_supported"
    assert json.loads(row["policy_ids"]) == ["N-RET"]
    assert row["model_provider"] == "fake" and row["fallback"] is False and row["model_used"] is True
    assert row["erp_status"] == "found"
    assert row["latency_ms"] == r["latency_ms"]
    assert row["created_at"].endswith("+00:00")  # UTC


def test_row_written_for_erp_fallback(client):
    r = triage(client, "northstar", "Return please", "NS-1-TIMEOUT").json()
    row = client.app.state.service.audit.get(r["request_id"])
    assert row["fallback"] is True and row["fallback_reason"] == "erp_timeout" and row["erp_status"] == "timeout"
    assert row["decision"] == "human_review"


def test_row_written_for_model_fallback(make_client):
    c = make_client(model=FakeProvider(mode="malformed"))
    r = triage(c, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231").json()
    row = c.app.state.service.audit.get(r["request_id"])
    assert row["fallback"] is True and row["fallback_reason"] == "model_malformed"
    assert json.loads(row["policy_ids"]) == []


def test_one_row_per_request_and_no_message_text(client):
    secret_msg = "My card number is 4111 1111 1111 1111, I want to return this."
    for i in range(3):
        triage(client, "northstar", secret_msg, "NS-88231", ticket_id=f"T-{i}")
    all_rows = rows(client)
    assert len(all_rows) == 3
    assert "4111" not in json.dumps(all_rows, default=str)


def test_discrepancies_recorded_in_audit(client):
    r = triage(client, "northstar", "I'd like to return this, it is unused.", "NS-88260", {"final_sale": False}).json()
    row = client.app.state.service.audit.get(r["request_id"])
    assert "final_sale: client=false, erp=true" in json.loads(row["discrepancies"])


def test_audit_failure_does_not_break_response(client, monkeypatch):
    def boom(**kw):
        raise RuntimeError("db down")
    monkeypatch.setattr(client.app.state.service.audit, "write", boom)
    r = triage(client, "northstar", "The jacket doesn't fit, I'd like to send it back.", "NS-88231")
    assert r.status_code == 200
