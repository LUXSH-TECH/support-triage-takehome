import csv
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


class ErpError(Exception):
    pass


class ErpTimeout(ErpError, TimeoutError):
    pass


@dataclass(frozen=True)
class OrderRecord:
    order_ref: str
    retailer: str
    delivery_date: date | None
    promised_date: date | None
    final_sale: bool | None
    item_condition: str | None  # UNUSED | USED | DAMAGED | None


class ErpClient(Protocol):
    """Swap FileErp for an HTTP / DB / queue client without touching the service."""

    def get_order(self, retailer: str, order_ref: str) -> OrderRecord | None: ...
    def ping(self) -> bool: ...


def _date(v: str) -> date | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return datetime.strptime(v, "%d-%m-%Y").date()
    except ValueError:
        return None  # garbage date == missing; never invent one


def _yn(v: str) -> bool | None:
    v = (v or "").strip().upper()
    return True if v == "Y" else False if v == "N" else None


class FileErp:
    """Simulated legacy ERP over the pipe-delimited feed.
    Test conventions: '<ref>-TIMEOUT' raises ErpTimeout; '<ref>-SLOW' sleeps, then returns <ref>."""

    def __init__(self, path, slow_delay_s: float = 0.05):
        self.slow_delay_s = slow_delay_s
        self._records: dict[tuple[str, str], OrderRecord] = {}
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f, delimiter="|"):
                rec = OrderRecord(
                    order_ref=row["order_ref"].strip().upper(),
                    retailer=row["retailer"].strip().lower(),
                    delivery_date=_date(row["delivery_date"]),
                    promised_date=_date(row["promised_date"]),
                    final_sale=_yn(row["final_sale"]),
                    item_condition=(row["item_condition"].strip().upper() or None),
                )
                # keyed by (retailer, ref): another retailer's order is simply not findable
                self._records[(rec.retailer, rec.order_ref)] = rec

    def get_order(self, retailer: str, order_ref: str) -> OrderRecord | None:
        ref = order_ref.strip().upper()
        if ref.endswith("-TIMEOUT"):
            raise ErpTimeout("simulated ERP timeout")
        if ref.endswith("-SLOW"):
            time.sleep(self.slow_delay_s)
            ref = ref[: -len("-SLOW")]
        return self._records.get((retailer, ref))

    def ping(self) -> bool:
        return bool(self._records)