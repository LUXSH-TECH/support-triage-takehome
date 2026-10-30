from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str
    northstar_api_key: str
    cedar_api_key: str
    today: date
    erp_path: Path
    fake_model_mode: str


def get_settings() -> Settings:
    database_path = (ROOT / "triage.db").as_posix()
    return Settings(
        database_url=os.getenv("DATABASE_URL", f"sqlite:///{database_path}"),
        northstar_api_key=os.getenv("NORTHSTAR_API_KEY", "test-key-northstar-001"),
        cedar_api_key=os.getenv("CEDAR_API_KEY", "test-key-cedar-002"),
        today=date.fromisoformat(os.getenv("TRIAGE_TODAY", "2025-09-01")),
        erp_path=Path(os.getenv("ERP_PATH", str(ROOT / "erp" / "orders.psv"))),
        fake_model_mode=os.getenv("FAKE_MODEL_MODE", "normal"),
    )