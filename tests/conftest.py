from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.services.erp_service import ErpOrder, InMemoryErpAdapter
from app.services.llm_service import FakeProvider
from app.main import create_app

TODAY = date(2025, 9, 1)
NS_KEY = "test-key-northstar-001"
CD_KEY = "test-key-cedar-002"
HEADERS = {"northstar": {"X-API-Key": NS_KEY}, "cedar": {"X-API-Key": CD_KEY}}


@pytest.fixture
def settings(tmp_path) -> Settings:
    return replace(Settings(), database_url=f"sqlite:///{tmp_path / 'test.db'}", erp_slow_delay_s=0.05)


@pytest.fixture
def make_client(settings):
    """Factory: build a client with optional ERP / model / settings overrides."""
    clients = []

    def _make(erp=None, model=None, **overrides) -> TestClient:
        s = replace(settings, **overrides) if overrides else settings
        c = TestClient(create_app(s, erp=erp, model=model or FakeProvider()))
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client) -> TestClient:
    """Real flat-file ERP fixture (erp/orders.psv) + deterministic fake model."""
    return make_client()


def triage(client: TestClient, retailer: str, message: str, order_ref: str | None = None, facts=None, ticket_id="T-1"):
    body = {"ticket_id": ticket_id, "message": message, "facts": facts or {}}
    if order_ref is not None:
        body["order_ref"] = order_ref
    return client.post("/triage", headers=HEADERS[retailer], json=body)


def order(ref, retailer, *, delivered_days_ago=None, overdue_days=None, final_sale=False, condition="UNUSED"):
    """Synthetic ERP order relative to the fixed reference date (for boundary tests)."""
    delivery = TODAY - timedelta(days=delivered_days_ago) if delivered_days_ago is not None else None
    promised = TODAY - timedelta(days=overdue_days) if overdue_days is not None else (delivery or TODAY)
    return ErpOrder(ref, retailer, None, delivery, promised, final_sale, condition, "web")


def memory_erp(*orders: ErpOrder) -> InMemoryErpAdapter:
    return InMemoryErpAdapter(list(orders))


def assert_verbatim(resp_json, policies_json):
    texts = {p["policy_id"]: p["text"] for p in policies_json}
    for c in resp_json["citations"]:
        assert c["excerpt"] in texts[c["policy_id"]], c
