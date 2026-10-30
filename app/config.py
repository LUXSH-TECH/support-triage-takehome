"""Runtime configuration.

All settings come from environment variables (12-factor) so the same image runs locally
and on Azure. Nothing here is a secret by default: the API-key map defaults to the fake
fixture keys from FIXTURES.md, and a real model key is only ever read from the
environment (``LLM_API_KEY``) — never committed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fixture keys (FIXTURES.md). Throwaway local values, not secrets. In Azure these come
# from Key Vault / APIM (see docs/AZURE_PLAN.md).
DEFAULT_API_KEYS = {
    "test-key-northstar-001": "northstar",
    "test-key-cedar-002": "cedar",
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./triage.db"
    policies_seed: Path = REPO_ROOT / "data" / "policies.json"
    erp_feed: Path = REPO_ROOT / "erp" / "orders.psv"
    reference_date: date = date(2025, 9, 1)
    erp_timeout_s: float = 2.0
    erp_slow_delay_s: float = 0.3
    request_budget_s: float = 20.0  # overall deadline for ERP + model work per request
    llm_provider: str = "fake"  # fake | openai | azure_openai
    llm_timeout_s: float = 8.0
    llm_max_retries: int = 0
    llm_model: str = ""
    llm_base_url: str = ""
    llm_api_key: str = field(default="", repr=False)
    llm_azure_deployment: str = ""
    llm_azure_api_version: str = "2024-10-21"
    fake_llm_mode: str = "ok"  # ok | timeout | malformed | unsafe  (tests/eval only)
    api_keys: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_API_KEYS), repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        keys_json = os.environ.get("API_KEYS_JSON")
        return cls(
            database_url=_env("DATABASE_URL", cls.database_url),
            policies_seed=Path(_env("POLICIES_SEED", str(cls.policies_seed))),
            erp_feed=Path(_env("ERP_FEED", str(cls.erp_feed))),
            reference_date=date.fromisoformat(_env("REFERENCE_DATE", cls.reference_date.isoformat())),
            erp_timeout_s=float(_env("ERP_TIMEOUT_S", str(cls.erp_timeout_s))),
            erp_slow_delay_s=float(_env("ERP_SLOW_DELAY_S", str(cls.erp_slow_delay_s))),
            request_budget_s=float(_env("REQUEST_BUDGET_S", str(cls.request_budget_s))),
            llm_provider=_env("LLM_PROVIDER", cls.llm_provider),
            llm_timeout_s=float(_env("LLM_TIMEOUT_S", str(cls.llm_timeout_s))),
            llm_max_retries=int(_env("LLM_MAX_RETRIES", str(cls.llm_max_retries))),
            llm_model=_env("LLM_MODEL", ""),
            llm_base_url=_env("LLM_BASE_URL", ""),
            llm_api_key=_env("LLM_API_KEY", ""),
            llm_azure_deployment=_env("LLM_AZURE_DEPLOYMENT", ""),
            llm_azure_api_version=_env("LLM_AZURE_API_VERSION", cls.llm_azure_api_version),
            fake_llm_mode=_env("FAKE_LLM_MODE", cls.fake_llm_mode),
            api_keys=json.loads(keys_json) if keys_json else dict(DEFAULT_API_KEYS),
        )
