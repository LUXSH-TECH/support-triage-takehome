from __future__ import annotations

from sqlalchemy import select

from app.database import triage_log_table


def request(client, order_ref: str = "NS-88231"):
    return client.post(
        "/triage",
        headers={"X-API-Key": "test-key-northstar-001"},
        json={
            "ticket_id": "T-FALLBACK",
            "order_ref": order_ref,
            "message": "I would like to return this item.",
        },
    )


def test_erp_timeout_returns_audited_human_review(client_factory) -> None:
    with client_factory() as client:
        response = request(client, "NS-88231-TIMEOUT")
        body = response.json()
        with client.app.state.database.engine.connect() as connection:
            rows = connection.execute(
                select(triage_log_table).where(
                    triage_log_table.c.request_id == body["request_id"]
                )
            ).mappings().all()
    assert response.status_code == 200
    assert body["decision"] == "human_review"
    assert body["model"]["fallback"] is True
    assert body["model"]["used"] is False
    assert body["citations"] == []
    assert body["fact_sources"] == {}
    assert len(rows) == 1
    assert rows[0]["fallback"] == 1


def test_slow_erp_response_still_returns_valid_result(client_factory) -> None:
    with client_factory() as client:
        response = request(client, "NS-88231-SLOW")
    assert response.status_code == 200
    assert response.json()["decision"] == "policy_supported"
    assert response.json()["model"]["fallback"] is False


def test_model_timeout_malformed_output_and_bad_citations_fall_back(client_factory) -> None:
    for mode in ("timeout", "malformed", "invalid_citation", "unsupported_claim"):
        with client_factory(model_mode=mode) as client:
            response = request(client)
            body = response.json()
            with client.app.state.database.engine.connect() as connection:
                rows = connection.execute(
                    select(triage_log_table).where(
                        triage_log_table.c.request_id == body["request_id"]
                    )
                ).mappings().all()
        assert response.status_code == 200
        assert body["decision"] == "human_review"
        assert body["model"]["provider"] == "fake"
        assert body["model"]["used"] is True
        assert body["model"]["fallback"] is True
        assert body["citations"] == []
        assert len(body["customer_response"]) <= 400
        assert len(rows) == 1
        assert rows[0]["fallback"] == 1


def test_citations_are_exact_stored_policy_substrings(client_factory) -> None:
    with client_factory() as client:
        response = request(client)
        body = response.json()
        with client.app.state.database.engine.connect() as connection:
            for citation in body["citations"]:
                policy_text = connection.exec_driver_sql(
                    "SELECT text FROM policy WHERE retailer = ? AND policy_id = ?",
                    ("northstar", citation["policy_id"]),
                ).scalar_one()
                assert citation["excerpt"] in policy_text


def test_invalid_policy_citation_is_rejected(client_factory) -> None:
    from app.model.interface import DraftCitation, ModelDraft
    from app.model.validation import InvalidDraft, validate_draft
    from app.repositories.policy_repository import Policy

    policy = Policy("N-RET", "northstar", "returns", "Unused items may be returned.")
    invalid = ModelDraft(
        "The order details meet the return policy.",
        (DraftCitation("N-RET", "Not a stored policy excerpt."),),
    )
    try:
        validate_draft(invalid, "northstar", policy)
    except InvalidDraft:
        pass
    else:
        raise AssertionError("invalid citation was accepted")


def test_response_validator_rejects_claims_and_long_responses() -> None:
    from app.model.interface import ModelDraft
    from app.model.validation import InvalidDraft, validate_draft

    for draft in (
        ModelDraft("Your refund is approved.", ()),
        ModelDraft("Your item is unused and eligible for return.", ()),
        ModelDraft("This is one. This is two. This is three. This is four.", ()),
        ModelDraft("This delivery was 400 days ago.", ()),
        ModelDraft("x" * 401, ()),
    ):
        try:
            validate_draft(
                draft,
                "northstar",
                None,
                {"unused": False},
                expected_response="This item does not meet the unused-item requirement for a return.",
            )
        except InvalidDraft:
            continue
        raise AssertionError("unsafe draft was accepted")