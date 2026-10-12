"""Relational store: schema, seed, and repositories.

SQLAlchemy Core (not the ORM) with bound parameters keeps SQL explicit and portable:
the same code runs on SQLite locally and on PostgreSQL Flexible Server / Azure SQL by
changing ``DATABASE_URL`` (plus the driver package). Types are deliberately plain
(String/Text/Integer/Boolean) to avoid dialect-specific features.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Column,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine

metadata = MetaData()

policy_table = Table(
    "policy",
    metadata,
    Column("policy_id", String(32), primary_key=True),
    Column("retailer", String(32), nullable=False),
    Column("category", String(32), nullable=False),
    Column("text", Text, nullable=False),
    Index("ix_policy_retailer_category", "retailer", "category"),
)

triage_log_table = Table(
    "triage_log",
    metadata,
    Column("request_id", String(64), primary_key=True),
    Column("ticket_id", String(64), nullable=False),
    Column("retailer", String(32), nullable=False),
    Column("order_ref", String(64)),
    Column("category", String(32)),
    Column("decision", String(32), nullable=False),
    Column("policy_ids", Text),  # JSON array of cited policy IDs
    Column("erp_status", String(32)),  # found | not_found | incomplete | timeout | error | skipped
    Column("discrepancies", Text),  # JSON array (fact names + values, no free text)
    Column("missing_information", Text),  # JSON array
    Column("model_provider", String(32)),
    Column("model_used", Boolean, nullable=False, default=False),
    Column("fallback", Boolean, nullable=False, default=False),
    Column("fallback_reason", String(64)),
    Column("latency_ms", Integer),
    Column("created_at", String(40), nullable=False),  # ISO-8601 UTC
    Index("ix_triage_log_created", "created_at"),
    Index("ix_triage_log_retailer_created", "retailer", "created_at"),
)


@dataclass(frozen=True)
class Policy:
    policy_id: str
    retailer: str
    category: str
    text: str


def make_engine(database_url: str) -> Engine:
    kwargs: dict = {"future": True, "pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


def init_db(engine: Engine, seed_path: Path) -> int:
    """Create tables and upsert the policy seed. Idempotent. Returns policy count.

    Locally this runs at startup. In Azure the same function is run as a one-off
    migration job before traffic is shifted (see docs/AZURE_PLAN.md).
    """
    metadata.create_all(engine)
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    with engine.begin() as conn:
        for p in seed:
            row = {k: p[k] for k in ("policy_id", "retailer", "category", "text")}
            conn.execute(policy_table.delete().where(policy_table.c.policy_id == row["policy_id"]))
            conn.execute(insert(policy_table).values(**row))
        return len(conn.execute(select(policy_table.c.policy_id)).all())


class PolicyRepository:
    """Retrieval is always scoped to the authenticated retailer in the WHERE clause."""

    def __init__(self, engine: Engine):
        self._engine = engine

    def for_category(self, retailer: str, category: str) -> list[Policy]:
        stmt = (
            select(policy_table)
            .where(policy_table.c.retailer == retailer)
            .where(policy_table.c.category == category)
            .order_by(policy_table.c.policy_id)
        )
        with self._engine.connect() as conn:
            return [Policy(**r._mapping) for r in conn.execute(stmt)]

    def for_retailer(self, retailer: str) -> dict[str, Policy]:
        """All policies of one retailer keyed by category (one query per request)."""
        stmt = select(policy_table).where(policy_table.c.retailer == retailer)
        with self._engine.connect() as conn:
            return {r.category: Policy(**r._mapping) for r in conn.execute(stmt)}

    def other_retailers(self, retailer: str) -> list[Policy]:
        """Used ONLY by the output guardrail to detect cross-retailer leakage in a draft;
        never used to answer a request."""
        stmt = select(policy_table).where(policy_table.c.retailer != retailer)
        with self._engine.connect() as conn:
            return [Policy(**r._mapping) for r in conn.execute(stmt)]

    def retailers(self) -> set[str]:
        with self._engine.connect() as conn:
            return {r[0] for r in conn.execute(select(policy_table.c.retailer).distinct())}

    def get(self, retailer: str, policy_id: str) -> Policy | None:
        stmt = select(policy_table).where(
            policy_table.c.retailer == retailer, policy_table.c.policy_id == policy_id
        )
        with self._engine.connect() as conn:
            row = conn.execute(stmt).first()
            return Policy(**row._mapping) if row else None

    def count(self) -> int:
        with self._engine.connect() as conn:
            return len(conn.execute(select(policy_table.c.policy_id)).all())

    def ping(self) -> bool:
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True


class AuditRepository:
    def __init__(self, engine: Engine):
        self._engine = engine

    def write(self, **row) -> None:
        for key in ("policy_ids", "discrepancies", "missing_information"):
            if key in row and not isinstance(row[key], str):
                row[key] = json.dumps(row[key])
        row.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        with self._engine.begin() as conn:
            conn.execute(insert(triage_log_table).values(**row))

    def get(self, request_id: str) -> dict | None:
        with self._engine.connect() as conn:
            r = conn.execute(
                select(triage_log_table).where(triage_log_table.c.request_id == request_id)
            ).first()
            return dict(r._mapping) if r else None

    def all(self) -> list[dict]:
        with self._engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(select(triage_log_table))]
