"""Derive order facts from the ERP (system of record) and reconcile client hints.

Rules (also in docs/DESIGN.md):

* Day counts and ``final_sale`` come **only** from the ERP. If the ERP lacks them they are
  reported as missing — a client hint never fills a decision-critical gap.
* ``unused`` comes from ERP ``item_condition`` (UNUSED/USED); if the ERP field is blank the
  client hint may be used and is labelled ``client`` in ``fact_sources``. DAMAGED sets
  ``damaged_in_erp`` and leaves ``unused`` underived (damaged != used).
* A record with neither delivery nor promised date is incomplete: delivery status unknown.
* ``photo_provided`` is not an ERP concept; it is always ``client``.
* When a client hint *materially* contradicts an ERP value, a discrepancy is recorded
  and the service routes to human review. Day counts tolerate ±1 day (timezone /
  cut-off differences) before counting as a contradiction.
* No ERP record (unknown, other retailer, timeout) => no order facts at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .erp import ErpOrder
from .schemas import ClientFacts

DAY_TOLERANCE = 1


@dataclass
class ResolvedFacts:
    values: dict[str, object] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    discrepancies: list[str] = field(default_factory=list)
    delivered: bool | None = None  # None = unknown (no ERP record)
    damaged_in_erp: bool = False
    incomplete_fields: list[str] = field(default_factory=list)

    def get(self, name: str):
        return self.values.get(name)

    def set(self, name: str, value, source: str) -> None:
        self.values[name] = value
        self.sources[name] = source


def _fmt(v) -> str:
    return str(v).lower() if isinstance(v, bool) else str(v)


def resolve_facts(order: ErpOrder | None, client: ClientFacts, today: date) -> ResolvedFacts:
    rf = ResolvedFacts()

    # photo_provided is customer-side information only.
    if client.photo_provided is not None:
        rf.set("photo_provided", client.photo_provided, "client")

    if order is None:
        return rf

    # --- delivery / overdue -------------------------------------------------------
    if order.delivery_date is not None:
        dsd = (today - order.delivery_date).days
        if dsd < 0:
            # Delivery dated after "today": a data error in the feed. Do not guess.
            rf.incomplete_fields.append("delivery_date")
        else:
            rf.delivered = True
            rf.set("days_since_delivery", dsd, "erp")
            # Delivered => not overdue (FIXTURES.md): history, not an open investigation.
            rf.set("days_overdue", 0, "erp")
    elif order.promised_date is not None:
        rf.delivered = False
        rf.set("days_overdue", max(0, (today - order.promised_date).days), "erp")
    else:
        # Neither date: we cannot tell "not yet delivered" from "date not recorded".
        rf.incomplete_fields += ["delivery_date", "promised_date"]

    # --- final sale ----------------------------------------------------------------
    if order.final_sale is not None:
        rf.set("final_sale", order.final_sale, "erp")
    else:
        rf.incomplete_fields.append("final_sale")

    # --- condition -----------------------------------------------------------------
    if order.item_condition in {"UNUSED", "USED"}:
        rf.set("unused", order.item_condition == "UNUSED", "erp")
    elif order.item_condition == "DAMAGED":
        # Damaged is not "used": unused is not derivable, and the damaged-item policy applies.
        rf.damaged_in_erp = True
    elif client.unused is not None:
        rf.set("unused", client.unused, "client")

    # --- reconciliation (client hint vs ERP) ----------------------------------------
    def conflict(name: str, client_val, erp_val) -> None:
        rf.discrepancies.append(f"{name}: client={_fmt(client_val)}, erp={_fmt(erp_val)}")

    if client.days_since_delivery is not None:
        erp_dsd = rf.values.get("days_since_delivery") if rf.sources.get("days_since_delivery") == "erp" else None
        if rf.delivered is False:
            conflict("days_since_delivery", client.days_since_delivery, "not_delivered")
        elif erp_dsd is not None and abs(erp_dsd - client.days_since_delivery) > DAY_TOLERANCE:
            conflict("days_since_delivery", client.days_since_delivery, erp_dsd)

    if client.days_overdue is not None and "days_overdue" in rf.values:
        erp_od = rf.values["days_overdue"]
        if rf.delivered and client.days_overdue > 0:
            conflict("days_overdue", client.days_overdue, "delivered")
        elif abs(erp_od - client.days_overdue) > DAY_TOLERANCE:
            conflict("days_overdue", client.days_overdue, erp_od)

    if client.final_sale is not None and order.final_sale is not None:
        if client.final_sale != order.final_sale:
            conflict("final_sale", client.final_sale, order.final_sale)

    if client.unused is not None and rf.sources.get("unused") == "erp":
        if client.unused != rf.values["unused"]:
            conflict("unused", client.unused, order.item_condition)

    # Client presents the item as an unused (i.e. returnable) item while the ERP marks it
    # final sale. Not a field-for-field clash, but a material contradiction about
    # returnability; the assignment's acceptance table treats it as one.
    if client.unused is True and order.final_sale is True and client.final_sale is None:
        rf.discrepancies.append("returnability: client=unused item, erp=final_sale")

    return rf
