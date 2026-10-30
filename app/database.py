from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import Column, Index, Integer, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool


metadata = MetaData()
policy_table = Table(
    "policy",
    metadata,
    Column("policy_id", String(32), primary_key=True),
    Column("retailer", String(32), nullable=False),
    Column("category", String(32), nullable=False),
    Column("text", Text, nullable=False),
)
Index("ix_policy_retailer", policy_table.c.retailer)
triage_log_table = Table(
    "triage_log",
    metadata,
    Column("request_id", String(36), primary_key=True),
    Column("ticket_id", String(128), nullable=False),
    Column("retailer", String(32), nullable=False),
    Column("category", String(32)),
    Column("decision", String(32), nullable=False),
    Column("policy_ids", Text, nullable=False),
    Column("model_provider", String(64), nullable=False),
    Column("fallback", Integer, nullable=False),
    Column("latency_ms", Integer, nullable=False),
    Column("created_at_utc", String(40), nullable=False),
)
Index("ix_triage_log_created", triage_log_table.c.created_at_utc)


class Database:
    def __init__(self, url: str) -> None:
        options: dict[str, object] = {"future": True}
        if url.endswith(":memory:") or url in {"sqlite://", "sqlite+pysqlite://"}:
            options["connect_args"] = {"check_same_thread": False}
            options["poolclass"] = StaticPool
        elif url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
        self.engine: Engine = create_engine(url, **options)

    def initialize(self, seed_path: Path) -> None:
        metadata.create_all(self.engine)
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        with self.engine.begin() as connection:
            for item in seed:
                existing = connection.execute(
                    select(policy_table.c.policy_id).where(policy_table.c.policy_id == item["policy_id"])
                ).first()
                values = {
                    "policy_id": item["policy_id"],
                    "retailer": item["retailer"],
                    "category": item["category"],
                    "text": item["text"],
                }
                if existing is None:
                    connection.execute(policy_table.insert().values(**values))
                else:
                    connection.execute(
                        policy_table.update()
                        .where(policy_table.c.policy_id == item["policy_id"])
                        .values(**values)
                    )

    def health_check(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            return True
        except Exception:
            return False