"""Writes one triage_log row per request (never the customer message)."""

from __future__ import annotations

import logging

from ..database import AuditRepository
from ..schemas import TriageResponse

log = logging.getLogger("triage")


def save_audit_log(
    audit: AuditRepository,
    response: TriageResponse,
    order_ref: str | None,
    erp_status: str,
    fallback_reason: str | None,
) -> None:
    try:
        audit.write(
            request_id=response.request_id,
            ticket_id=response.ticket_id,
            retailer=response.retailer,
            order_ref=order_ref,
            category=response.category,
            decision=response.decision,
            policy_ids=sorted({c.policy_id for c in response.citations}),
            erp_status=erp_status,
            discrepancies=response.discrepancies,
            missing_information=response.missing_information,
            model_provider=response.model.provider,
            model_used=response.model.used,
            fallback=response.model.fallback,
            fallback_reason=fallback_reason,
            latency_ms=response.latency_ms,
        )
    except Exception:
        # A failed audit write is logged loudly (alertable) but does not fail the request.
        log.exception("audit write failed request_id=%s", response.request_id)
