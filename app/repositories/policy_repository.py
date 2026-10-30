from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select

from app.database import Database, policy_table


@dataclass(frozen=True)
class Policy:
    policy_id: str
    retailer: str
    category: str
    text: str


class PolicyRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def get(self, retailer: str, category: str) -> Policy | None:
        statement = select(policy_table).where(
            policy_table.c.retailer == retailer,
            policy_table.c.category == category,
        )
        with self.database.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            return None
        return Policy(**row)

    def get_by_id(self, retailer: str, policy_id: str) -> Policy | None:
        statement = select(policy_table).where(
            policy_table.c.retailer == retailer,
            policy_table.c.policy_id == policy_id,
        )
        with self.database.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return Policy(**row) if row is not None else None

    @staticmethod
    def citation_excerpt(policy: Policy, sentence_index: int = 0) -> str:
        sentences = re.split(r"(?<=\.)\s+", policy.text)
        if sentence_index >= len(sentences):
            return policy.text
        return sentences[sentence_index]