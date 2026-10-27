import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    db_path: str = str(ROOT / "triage.db")
    schema_path: Path = ROOT / "data" / "schema.sql"
    policies_path: Path = ROOT / "data" / "policies.json"
    erp_path: Path = ROOT / "erp" / "orders.psv"
    today: date = date(2025, 9, 1)  # fixed "today" -> deterministic tests
    # throwaway test keys from FIXTURES.md; identity comes ONLY from this map
    api_keys: dict = field(default_factory=lambda: {
        "test-key-northstar-001": "northstar",
        "test-key-cedar-002": "cedar",
    })
    erp_timeout_s: float = 2.0
    model_timeout_s: float = 8.0
    model_provider: str = "fake"  # fake | http

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.getenv("TRIAGE_DB", str(ROOT / "triage.db")),
            model_provider=os.getenv("MODEL_PROVIDER", "fake"),
        )