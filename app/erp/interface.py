from __future__ import annotations

from datetime import date
from typing import Protocol


class ERPRecord(Protocol):
    order_ref: str

    def facts(self, today: date) -> dict[str, object | None]:
        ...


class ERPClient(Protocol):
    def get_order(self, retailer: str, order_ref: str) -> ERPRecord | None:
        ...

    def health_check(self) -> bool:
        ...