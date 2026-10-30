from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class Order:
    order_ref: str
    retailer: str
    delivery_date: date | None
    promised_date: date | None
    final_sale: bool | None
    item_condition: str | None

    def facts(self, today: date) -> dict[str, object | None]:
        days_since_delivery = (
            max(0, (today - self.delivery_date).days) if self.delivery_date is not None else None
        )
        if self.delivery_date is not None:
            days_overdue = 0
        elif self.promised_date is not None:
            days_overdue = max(0, (today - self.promised_date).days)
        else:
            days_overdue = None

        if self.item_condition == "UNUSED":
            unused: bool | None = True
        elif self.item_condition == "USED":
            unused = False
        else:
            unused = None

        return {
            "days_since_delivery": days_since_delivery,
            "days_overdue": days_overdue,
            "final_sale": self.final_sale,
            "unused": unused,
        }


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%d-%m-%Y").date()


class MockERP:
    def __init__(self, path: Path, slow_delay_seconds: float = 0.02) -> None:
        self.path = path
        self.slow_delay_seconds = slow_delay_seconds
        self._orders: dict[tuple[str, str], Order] = {}
        with path.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source, delimiter="|"):
                retailer = row["retailer"].strip().lower()
                order = Order(
                    order_ref=row["order_ref"].strip(),
                    retailer=retailer,
                    delivery_date=_parse_date(row["delivery_date"].strip()),
                    promised_date=_parse_date(row["promised_date"].strip()),
                    final_sale={"Y": True, "N": False}.get(row["final_sale"].strip()),
                    item_condition=row["item_condition"].strip() or None,
                )
                self._orders[(retailer, order.order_ref)] = order

    def get_order(self, retailer: str, order_ref: str) -> Order | None:
        suffix = order_ref.upper()
        if suffix.endswith("-TIMEOUT"):
            raise TimeoutError("simulated ERP timeout")
        if suffix.endswith("-SLOW"):
            time.sleep(self.slow_delay_seconds)
            base_order_ref = order_ref[:-5]
        else:
            base_order_ref = order_ref
        return self._orders.get((retailer, base_order_ref))

    def health_check(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 0