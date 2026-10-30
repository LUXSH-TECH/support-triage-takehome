"""The triage flow, step by step. Called by routes/triage_routes.py.

    Step 1  classify the message            -> classifier_service
    Step 2  look up the order in the ERP    -> erp_service
    Step 3  reconcile customer facts vs ERP -> facts_service
    Step 4  load this retailer's policies   -> database (PolicyRepository)
    Step 5  decide the outcome (in code)    -> policy_service
    Step 6  draft the reply with the model  -> llm_service (+ guardrail_service)
    Step 7  double-check citations          -> database
    Step 8  save the audit row              -> audit_service

If anything fails (ERP down, model timeout, bad model output, unexpected bug), the
ticket gets the safe "fallback": decision = human_review, no advice, no citations.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from ..context import AppContext
from ..schemas import TriageRequest, TriageResponse
from .audit_service import save_audit_log
from .classifier_service import classify
from .erp_service import lookup_order
from .facts_service import ResolvedFacts, resolve_facts
from .llm_service import ModelError, draft_customer_reply
from .policy_service import Outcome, choose_outcome, fallback_outcome

log = logging.getLogger("triage")


@dataclass
class TriageResult:
    """What we have worked out so far for one ticket."""

    category: str = "other"
    outcome: Outcome = field(default_factory=lambda: fallback_outcome("not_started"))
    facts: ResolvedFacts = field(default_factory=ResolvedFacts)
    reply: str = ""
    erp_status: str = "skipped"
    model_used: bool = False
    fallback_reason: str | None = None

    def use_fallback(self, reason: str, clear_facts: bool = False) -> None:
        self.fallback_reason = reason
        self.outcome = fallback_outcome(reason)
        self.reply = self.outcome.draft
        if clear_facts:
            self.facts = ResolvedFacts()


async def run_triage(req: TriageRequest, retailer: str, ctx: AppContext) -> TriageResponse:
    started = time.perf_counter()
    request_id = uuid.uuid4().hex
    result = TriageResult()

    try:
        await _run_steps(req, retailer, ctx, result, started)
    except Exception:
        log.exception("unexpected error request_id=%s", request_id)
        result.use_fallback("internal_error", clear_facts=True)

    response = _build_response(req, retailer, request_id, result, ctx, started)

    # Step 8: audit row (always written, even for fallbacks)
    await asyncio.to_thread(save_audit_log, ctx.audit, response, req.order_ref, result.erp_status, result.fallback_reason)
    return response


async def _run_steps(req: TriageRequest, retailer: str, ctx: AppContext, result: TriageResult, started: float) -> None:
    settings = ctx.settings

    # Step 1: what is the ticket about?
    classification = classify(req.message)
    result.category = classification.category

    # Step 2: get the order from the ERP (only this retailer's orders are visible)
    order, result.erp_status = await lookup_order(ctx.erp, req.order_ref, retailer, settings.erp_timeout_s)
    if result.erp_status in ("timeout", "error"):
        result.use_fallback(f"erp_{result.erp_status}", clear_facts=True)
        return

    # Step 3: work out the facts; the ERP wins, contradictions are recorded
    result.facts = resolve_facts(order, req.facts, settings.reference_date)
    if order is not None and result.facts.incomplete_fields:
        result.erp_status = "incomplete"

    # Step 4: this retailer's policies only (WHERE retailer = ...)
    policies = await asyncio.to_thread(ctx.policies.for_retailer, retailer)

    # Step 5: decide, in code
    result.category, result.outcome = choose_outcome(
        category=classification.category,
        unsupported=classification.unsupported,
        mixed=classification.mixed,
        order_found=order is not None,
        order_ref_given=bool(req.order_ref),
        retailer=retailer,
        policies=policies,
        facts=result.facts,
    )

    # Step 6: the model only rewrites the approved reply; its output is checked
    result.model_used = True
    try:
        other_policies = await asyncio.to_thread(ctx.policies.other_retailers, retailer)
        result.reply = await draft_customer_reply(
            model=ctx.model,
            settings=settings,
            retailer=retailer,
            outcome=result.outcome,
            facts=result.facts,
            customer_message=req.message,
            own_policies=list(policies.values()),
            other_policies=other_policies,
            seconds_left=settings.request_budget_s - (time.perf_counter() - started),
        )
    except ModelError as exc:
        result.use_fallback(f"model_{exc.reason}")
        return
    except Exception:
        log.exception("model provider failure")
        result.use_fallback("model_error")
        return

    # Step 7: every citation must be an exact substring of the stored policy text
    for c in result.outcome.citations:
        policy = ctx.policies.get(retailer, c["policy_id"])
        if policy is None or c["excerpt"] not in policy.text:
            result.use_fallback("citation_verification_failed")
            return


def _build_response(req, retailer, request_id, result: TriageResult, ctx: AppContext, started: float) -> TriageResponse:
    def build() -> TriageResponse:
        facts = result.facts
        return TriageResponse(
            ticket_id=req.ticket_id,
            request_id=request_id,
            retailer=retailer,
            category=result.category,
            decision=result.outcome.decision,
            next_action=result.outcome.next_action,
            customer_response=result.reply or result.outcome.draft,
            citations=result.outcome.citations,
            missing_information=result.outcome.missing,
            fact_sources={k: facts.sources[k] for k in result.outcome.used_facts if k in facts.sources},
            discrepancies=facts.discrepancies,
            model={"provider": ctx.model.name, "used": result.model_used, "fallback": result.fallback_reason is not None},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    try:
        return build()
    except Exception:  # never return something that breaks the response contract
        log.exception("response validation failed request_id=%s", request_id)
        result.use_fallback("output_validation_failed", clear_facts=True)
        return build()
