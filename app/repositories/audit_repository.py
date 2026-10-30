from __future__ import annotations

import json
from datetime import datetime, timezone

from app.database import Database, triage_log_table


class AuditRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def write(
        self,
        *,
        request_id: str,
        ticket_id: str,
        retailer: str,
        category: str,
        decision: str,
        policy_ids: list[str],
        model_provider: str,
        fallback: bool,
        latency_ms: int,
    ) -> None:
        values = {
            "request_id": request_id,
            "ticket_id": ticket_id,
            "retailer": retailer,
            "category": category,
            "decision": decision,
            "policy_ids": json.dumps(policy_ids),
            "model_provider": model_provider,
            "fallback": int(fallback),
            "latency_ms": latency_ms,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        with self.database.engine.begin() as connection:
            connection.execute(triage_log_table.insert().values(**values))