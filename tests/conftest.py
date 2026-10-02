import sqlite3
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

NS = {"X-API-Key": "test-key-northstar-001"}
CD = {"X-API-Key": "test-key-cedar-002"}
TODAY = date(2025, 9, 1)
HEADER = "order_ref|retailer|order_date|delivery_date|promised_date|final_sale|item_condition|channel"


def ago(days: int) -> str:
    return (TODAY - timedelta(days=days)).strftime("%d-%m-%Y")


@pytest.fixture
def make_client(tmp_path):
    def _make(erp=None, provider=None):
        settings = Settings(db_path=str(tmp_path / "t.db"))
        return TestClient(create_app(settings, erp=erp, provider=provider)), settings
    return _make


@pytest.fixture
def client(make_client):
    return make_client()[0]


@pytest.fixture
def psv_client(make_client, tmp_path):
    """Client backed by a generated ERP feed so day-count edges are exact."""
    from app.erp import FileErp

    def _make(rows: list[str]):
        path = tmp_path / "orders.psv"
        path.write_text("\n".join([HEADER, *rows]) + "\n")
        return make_client(erp=FileErp(path))[0]
    return _make


def post(client, headers, message, order_ref, facts=None, ticket="T-1"):
    body = {"ticket_id": ticket, "order_ref": order_ref, "message": message}
    if facts is not None:
        body["facts"] = facts
    return client.post("/triage", headers=headers, json=body)


def log_rows(settings):
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM triage_log ORDER BY created_at")]
    conn.close()
    return rows