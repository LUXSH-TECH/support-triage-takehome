import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Policy:
    policy_id: str
    retailer: str
    category: str
    text: str


class Repository:
    """All SQL lives here. Plain parameterised SQL -> swap the driver/paramstyle
    (or move to SQLAlchemy Core) to run on Azure SQL / PostgreSQL."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=5)  # one short-lived conn per call: thread-safe
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self, schema_path: Path, policies_path: Path) -> None:
        policies = json.loads(Path(policies_path).read_text(encoding="utf-8"))
        with self._conn() as c:
            c.executescript(Path(schema_path).read_text(encoding="utf-8"))
            for p in policies:  # idempotent seed: re-running at every startup is safe
                c.execute(
                    """INSERT INTO policy (policy_id, retailer, category, text)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(policy_id) DO UPDATE SET
                         retailer=excluded.retailer, category=excluded.category, text=excluded.text""",
                    (p["policy_id"], p["retailer"], p["category"], p["text"]),
                )

    def get_policy(self, retailer: str, category: str) -> Policy | None:
        # retailer isolation at query level: the WHERE clause is the boundary
        with self._conn() as c:
            row = c.execute(
                "SELECT policy_id, retailer, category, text FROM policy WHERE retailer = ? AND category = ?",
                (retailer, category),
            ).fetchone()
        return Policy(**dict(row)) if row else None

    def all_policies(self) -> list[Policy]:  # used only by the evaluation script
        with self._conn() as c:
            return [Policy(**dict(r)) for r in c.execute("SELECT policy_id, retailer, category, text FROM policy")]

    def log_triage(self, *, request_id, ticket_id, retailer, category, decision,
                   policy_ids, model_provider, fallback, latency_ms) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT INTO triage_log (request_id, ticket_id, retailer, category, decision,
                       policy_ids, model_provider, fallback, latency_ms, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (request_id, ticket_id, retailer, category, decision, json.dumps(policy_ids),
                 model_provider, int(fallback), latency_ms, datetime.now(timezone.utc).isoformat()),
            )

    def ping(self) -> bool:
        try:
            with self._conn() as c:
                c.execute("SELECT 1 FROM policy LIMIT 1").fetchone()
            return True
        except Exception:
            return False