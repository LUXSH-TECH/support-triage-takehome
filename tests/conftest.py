from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import ROOT, Settings
from app.erp.mock_erp import MockERP
from app.main import create_app
from app.model.fake import FakeModelProvider


ERP_FILE = ROOT / "erp" / "orders.psv"


@pytest.fixture
def client_factory(tmp_path: Path):
    def make_client(*, model_mode: str = "normal", erp: MockERP | None = None) -> TestClient:
        database_path = (tmp_path / f"{uuid.uuid4()}.db").as_posix()
        settings = Settings(
            database_url=f"sqlite:///{database_path}",
            northstar_api_key="test-key-northstar-001",
            cedar_api_key="test-key-cedar-002",
            today=date(2025, 9, 1),
            erp_path=ERP_FILE,
            fake_model_mode=model_mode,
        )
        application = create_app(
            settings,
            erp=erp or MockERP(ERP_FILE),
            model_provider=FakeModelProvider(model_mode),
        )
        return TestClient(application)

    return make_client