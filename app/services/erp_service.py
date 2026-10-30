"""Legacy ERP integration.

``ErpAdapter`` is the seam: the service depends only on ``get_order(order_ref, retailer)``
and ``ping()``. ``FlatFileErpAdapter`` reads the pipe-delimited legacy feed; an Azure
deployment would swap in an HTTP/DB/queue-backed adapter without touching the service.

Simulated failure convention (documented in README):
  * ``<ref>-TIMEOUT`` -> raises ``ErpTimeout`` immediately.
  * ``<ref>-SLOW``    -> sleeps ``slow_delay_s`` then returns the record for ``<ref>``.
    The service applies its own wall-clock timeout, so if ``slow_delay_s`` exceeds
    ``ERP_TIMEOUT_S`` a SLOW lookup becomes a real timeout.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Protocol


class ErpError(Exception):
    """ERP unavailable or returned something unusable."""


class ErpTimeout(ErpError):
    """ERP did not answer in time."""


@dataclass(frozen=True)
class ErpOrder:
    order_ref: str
    retailer: str  # normalised lower-case
    order_date: date | None
    delivery_date: date | None
    promised_date: date | None
    final_sale: bool | None
    item_condition: str | None  # UNUSED | USED | DAMAGED | None
    channel: str | None


class ErpAdapter(Protocol):
    def get_order(self, order_ref: str, retailer: str) -> ErpOrder | None: ...

    def ping(self) -> bool: ...


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d-%m-%Y").date()
    except ValueError:
        # Malformed date in a legacy feed is treated as missing, never guessed.
        return None


def _parse_flag(value: str) -> bool | None:
    value = (value or "").strip().upper()
    return {"Y": True, "N": False}.get(value)


def _parse_condition(value: str) -> str | None:
    value = (value or "").strip().upper()
    return value if value in {"UNUSED", "USED", "DAMAGED"} else None


def parse_row(row: dict[str, str]) -> ErpOrder:
    return ErpOrder(
        order_ref=row["order_ref"].strip(),
        retailer=row["retailer"].strip().lower(),
        order_date=_parse_date(row.get("order_date", "")),
        delivery_date=_parse_date(row.get("delivery_date", "")),
        promised_date=_parse_date(row.get("promised_date", "")),
        final_sale=_parse_flag(row.get("final_sale", "")),
        item_condition=_parse_condition(row.get("item_condition", "")),
        channel=(row.get("channel") or "").strip() or None,
    )


class FlatFileErpAdapter:
    def __init__(self, feed_path: Path, slow_delay_s: float = 0.3):
        self._path = Path(feed_path)
        self._slow_delay_s = slow_delay_s

    def _read_all(self) -> dict[str, ErpOrder]:
        # Re-read per lookup: the file is tiny, and this mimics a live system of record
        # (an updated feed is picked up without restart).
        try:
            with self._path.open(newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh, delimiter="|")
                return {o.order_ref.upper(): o for o in map(parse_row, reader)}
        except OSError as exc:
            raise ErpError(f"ERP feed unavailable: {exc.__class__.__name__}") from exc

    def get_order(self, order_ref: str, retailer: str) -> ErpOrder | None:
        ref = order_ref.strip().upper()  # legacy refs are case-insensitive
        if ref.endswith("-TIMEOUT"):
            raise ErpTimeout("simulated ERP timeout")
        if ref.endswith("-SLOW"):
            time.sleep(self._slow_delay_s)
            ref = ref[: -len("-SLOW")]
        order = self._read_all().get(ref)
        # Retailer isolation at the data layer: another retailer's order is "not found",
        # indistinguishable from a genuinely unknown reference.
        if order is None or order.retailer != retailer:
            return None
        return order

    def ping(self) -> bool:
        return self._path.is_file()


class InMemoryErpAdapter:
    """Test double with the same isolation semantics."""

    def __init__(self, orders: list[ErpOrder]):
        self._orders = {o.order_ref: o for o in orders}

    def get_order(self, order_ref: str, retailer: str) -> ErpOrder | None:
        if order_ref.upper().endswith("-TIMEOUT"):
            raise ErpTimeout("simulated ERP timeout")
        o = self._orders.get(order_ref)
        return o if o is not None and o.retailer == retailer else None

    def ping(self) -> bool:
        return True


# ---------------------------------------------------------------------------------------
# Main entry point used by triage_service.
# ---------------------------------------------------------------------------------------

async def lookup_order(erp: ErpAdapter, order_ref: str | None, retailer: str, timeout_s: float):
    """Look up an order for the authenticated retailer, with a hard timeout.

    Returns (order, status) where status is one of:
    skipped (no ref) | found | not_found | timeout | error.
    """
    if not order_ref:
        return None, "skipped"
    try:
        order = await asyncio.wait_for(asyncio.to_thread(erp.get_order, order_ref, retailer), timeout=timeout_s)
        return order, ("found" if order else "not_found")
    except (ErpTimeout, asyncio.TimeoutError):
        return None, "timeout"
    except ErpError:
        return None, "error"
    except Exception:  # unexpected adapter bug: still a bounded outcome
        logging.getLogger("triage").exception("erp adapter failure")
        return None, "error"
