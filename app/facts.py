from dataclasses import dataclass, field
from datetime import date

from app.erp import OrderRecord
from app.models import Discrepancy, Facts

# Only facts that can change the decision for a category are reconciled ("material").
RELEVANT = {
    "returns": ("days_since_delivery", "final_sale", "unused"),
    "damaged_item": ("days_since_delivery", "photo_provided"),
    "shipping": ("days_overdue", "days_since_delivery"),
}


@dataclass
class ErpFacts:
    values: dict = field(default_factory=dict)  # only facts the ERP actually knows
    undelivered: bool = False                   # blank delivery_date but a promised_date exists
    damaged: bool = False                       # item_condition == DAMAGED


@dataclass
class Resolved:
    values: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    discrepancies: list = field(default_factory=list)


def derive_erp_facts(rec: OrderRecord, today: date) -> ErpFacts:
    f = ErpFacts(damaged=rec.item_condition == "DAMAGED")
    if rec.delivery_date:
        days = (today - rec.delivery_date).days
        if days >= 0:  # a delivery date in the future is bad data -> treat as unknown
            f.values["days_since_delivery"] = days
            f.values["days_overdue"] = 0  # delivered => history, never an open shipping case
    elif rec.promised_date:
        f.undelivered = True
        f.values["days_overdue"] = max(0, (today - rec.promised_date).days)
    if rec.final_sale is not None:
        f.values["final_sale"] = rec.final_sale
    if rec.item_condition == "UNUSED":
        f.values["unused"] = True
    elif rec.item_condition == "USED":
        f.values["unused"] = False
    return f


def reconcile(category: str, client: Facts, erp: ErpFacts) -> Resolved:
    """ERP is the system of record. ERP value wins; a differing client value is recorded
    as a discrepancy. The client only fills gaps the ERP leaves blank."""
    out = Resolved()
    for name in RELEVANT.get(category, ()):
        c = getattr(client, name)
        e = erp.values.get(name)
        if e is not None:
            out.values[name], out.sources[name] = e, "erp"
            if c is not None and c != e:
                out.discrepancies.append(Discrepancy(fact=name, client=c, erp=e))
        elif c is not None:
            if name == "days_since_delivery" and erp.undelivered:
                out.discrepancies.append(Discrepancy(fact=name, client=c, erp="not_delivered"))
            else:
                out.values[name], out.sources[name] = c, "client"
    return out