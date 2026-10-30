from __future__ import annotations

from datetime import date
from app.config import ROOT
from app.erp.mock_erp import MockERP, Order
from app.services.reconciliation import reconcile


def test_fixture_erp_derives_dates_and_authoritative_facts() -> None:
    erp = MockERP(ROOT / "erp" / "orders.psv")
    delivered = erp.get_order("northstar", "NS-88231")
    assert delivered is not None
    assert delivered.facts(date(2025, 9, 1)) == {
        "days_since_delivery": 20,
        "days_overdue": 0,
        "final_sale": False,
        "unused": True,
    }
    undelivered = erp.get_order("northstar", "NS-88255")
    assert undelivered is not None
    assert undelivered.facts(date(2025, 9, 1))["days_overdue"] == 6


def test_missing_incomplete_slow_and_timeout_erp_behaviors() -> None:
    erp = MockERP(ROOT / "erp" / "orders.psv", slow_delay_seconds=0)
    assert erp.get_order("northstar", "UNKNOWN") is None
    assert erp.get_order("cedar", "NS-88231") is None
    incomplete = erp.get_order("northstar", "NS-88270")
    assert incomplete is not None
    assert incomplete.facts(date(2025, 9, 1))["days_overdue"] is None
    assert erp.get_order("northstar", "NS-88231-SLOW") is not None
    try:
        erp.get_order("northstar", "NS-88231-TIMEOUT")
    except TimeoutError:
        pass
    else:
        raise AssertionError("timeout convention was not honored")


def test_missing_erp_facts_do_not_fall_back_to_client_values() -> None:
    order = Order("X", "northstar", None, None, None, None)
    result = reconcile(
        order.facts(date(2025, 9, 1)),
        {
            "days_since_delivery": 20,
            "days_overdue": 0,
            "unused": True,
            "final_sale": False,
        },
    )
    assert result.facts == {}
    assert result.fact_sources == {}
    assert result.discrepancies == []


def test_matching_client_facts_keep_erp_provenance_and_photo_client_provenance() -> None:
    result = reconcile(
        {
            "days_since_delivery": 20,
            "days_overdue": 0,
            "unused": True,
            "final_sale": False,
        },
        {
            "days_since_delivery": 20,
            "days_overdue": 0,
            "unused": True,
            "final_sale": False,
            "photo_provided": False,
        },
    )
    assert result.discrepancies == []
    assert all(result.fact_sources[field] == "erp" for field in (
        "days_since_delivery", "days_overdue", "unused", "final_sale"
    ))
    assert result.fact_sources["photo_provided"] == "client"


def test_contradictory_client_fact_is_recorded_but_erp_wins() -> None:
    result = reconcile(
        {"days_since_delivery": 20, "days_overdue": 0, "unused": True, "final_sale": True},
        {"unused": True, "final_sale": False},
    )
    assert result.facts["final_sale"] is True
    assert result.fact_sources["final_sale"] == "erp"
    assert result.discrepancies == [
        {"field": "final_sale", "client_value": False, "erp_value": True}
    ]