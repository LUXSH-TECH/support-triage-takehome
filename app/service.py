"""Triage orchestration: classify -> ERP lookup -> reconcile -> retrieve -> decide ->
draft (model) -> validate -> audit.

Routing precedence (first match wins):
  1. ERP timeout / error                       -> bounded fallback (human_review)
  2. unsupported topic or category "other"     -> human_review
  3. mixed issue (several categories)          -> human_review
  4. no order_ref / order not found            -> needs_information
  5. client facts contradict the ERP           -> human_review (+ discrepancies)
  6. policy engine decision (an ERP record missing ERP-only facts -> human_review)
  then: model failure / unsafe draft / citation check failure -> bounded fallback.
Any unexpected exception anywhere -> bounded fallback ("internal_error"); the audit row
is written on every path.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from .classifier import classify
from .config import Settings
from .db import AuditRepository, Policy, PolicyRepository
from .erp import ErpAdapter, ErpError, ErpTimeout
from .facts import ResolvedFacts, resolve_facts
from .guardrails import validate_draft
from .llm import DraftRequest, ModelError, ModelProvider
from .policy_engine import HUMAN_REVIEW_MESSAGE, RULES, Outcome, decide, excerpt, human, needs_info
from .schemas import TriageRequest, TriageResponse

log = logging.getLogger("triage")

REQUIRED_FACTS = {
    "returns": ["days_since_delivery", "final_sale", "unused"],
    "damaged_item": ["days_since_delivery", "photo_provided"],
    "shipping": ["days_overdue"],
}


def fallback_outcome(reason: str) -> Outcome:
    return Outcome(
        decision="human_review",
        reason=reason,
        next_action=f"Bounded fallback ({reason}): route to an agent. No automated advice was given.",
        draft=HUMAN_REVIEW_MESSAGE,
    )


@dataclass
class _State:
    category: str = "other"
    outcome: Outcome = field(default_factory=lambda: fallback_outcome("not_started"))
    facts: ResolvedFacts = field(default_factory=ResolvedFacts)
    erp_status: str = "skipped"
    fallback_reason: str | None = None
    model_used: bool = False
    customer_response: str = HUMAN_REVIEW_MESSAGE

    def fall_back(self, reason: str, drop_facts: bool = False) -> None:
        self.fallback_reason = reason
        self.outcome = fallback_outcome(reason)
        self.customer_response = self.outcome.draft
        if drop_facts:
            self.facts = ResolvedFacts()


@dataclass
class TriageService:
    settings: Settings
    policies: PolicyRepository
    audit: AuditRepository
    erp: ErpAdapter
    model: ModelProvider

    async def triage(self, req: TriageRequest, retailer: str) -> TriageResponse:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        st = _State()
        try:
            await self._run(req, retailer, st, started)
        except Exception:
            log.exception("triage pipeline failure request_id=%s", request_id)
            st.fall_back("internal_error", drop_facts=True)

        response = self._build_response(req, retailer, request_id, st, started)
        await asyncio.to_thread(self._write_audit, response, req, st.erp_status, st.fallback_reason)
        return response

    # ------------------------------------------------------------------ pipeline
    async def _run(self, req: TriageRequest, retailer: str, st: _State, started: float) -> None:
        cls = classify(req.message)
        st.category = cls.category

        # ---- ERP lookup (system of record), isolated to the authenticated retailer ----
        order = None
        if req.order_ref:
            try:
                order = await asyncio.wait_for(
                    asyncio.to_thread(self.erp.get_order, req.order_ref, retailer),
                    timeout=self.settings.erp_timeout_s,
                )
                st.erp_status = "found" if order else "not_found"
            except (ErpTimeout, asyncio.TimeoutError):
                st.erp_status = "timeout"
            except ErpError:
                st.erp_status = "error"
            except Exception:  # unexpected adapter bug: still a bounded outcome
                log.exception("erp adapter failure")
                st.erp_status = "error"

        st.facts = resolve_facts(order, req.facts, self.settings.reference_date)
        if order is not None and st.facts.incomplete_fields:
            st.erp_status = "incomplete"

        if st.erp_status in {"timeout", "error"}:
            st.fall_back(f"erp_{st.erp_status}", drop_facts=True)
            return

        own = await asyncio.to_thread(self.policies.for_retailer, retailer)
        if cls.unsupported or st.category == "other":
            st.outcome = human(
                "unsupported_or_ambiguous",
                "Route to an agent: request is outside supported policies or is ambiguous.",
            )
        elif cls.mixed:
            st.outcome = human("mixed_issue", "Route to an agent: ticket mixes more than one issue type.")
        elif order is None:
            st.outcome = needs_info("order_not_found", ["order_ref"] + REQUIRED_FACTS[st.category], [], [])
            st.outcome.draft = (
                "Thanks for getting in touch. We could not find an order matching the details "
                "provided; could you please double-check and send us your order number?"
                if req.order_ref
                else "Thanks for getting in touch. Could you please send us your order number so we can look into this?"
            )
        else:
            if st.category == "returns" and st.facts.damaged_in_erp:
                # "Damaged items follow the damaged-item policy."
                st.category = "damaged_item"
                st.outcome = decide(st.category, retailer, own.get(st.category), st.facts)
                if "returns" in own:
                    st.outcome.citations.insert(0, excerpt(own["returns"], 2))
            else:
                st.outcome = decide(st.category, retailer, own.get(st.category), st.facts)

            if st.facts.discrepancies:
                st.outcome = human(
                    "client_erp_discrepancy",
                    "Route to an agent: client-supplied facts contradict the ERP; no outcome promised.",
                    st.outcome.citations,
                    list(st.facts.sources),
                )

        # ---- drafting via model ----
        st.model_used = True
        st.customer_response = st.outcome.draft
        try:
            st.customer_response = await self._draft(req, retailer, st.outcome, st.facts, own, started)
        except ModelError as exc:
            st.fall_back(f"model_{exc.reason}")
            return
        except Exception:
            log.exception("model provider failure")
            st.fall_back("model_error")
            return

        # ---- verify every citation verbatim against the stored policy text ----
        if not await asyncio.to_thread(self._citations_verified, retailer, st.outcome.citations):
            st.fall_back("citation_verification_failed")

    # ------------------------------------------------------------------ helpers
    def _build_response(self, req, retailer, request_id, st: _State, started: float) -> TriageResponse:
        def build() -> TriageResponse:
            return TriageResponse(
                ticket_id=req.ticket_id,
                request_id=request_id,
                retailer=retailer,
                category=st.category,
                decision=st.outcome.decision,
                next_action=st.outcome.next_action,
                customer_response=st.customer_response,
                citations=st.outcome.citations,
                missing_information=st.outcome.missing,
                fact_sources={k: st.facts.sources[k] for k in st.outcome.used_facts if k in st.facts.sources},
                discrepancies=st.facts.discrepancies,
                model={"provider": self.model.name, "used": st.model_used, "fallback": st.fallback_reason is not None},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )

        try:
            return build()
        except Exception:  # output validation failed: never return an invalid contract
            log.exception("response validation failed request_id=%s", request_id)
            st.fall_back("output_validation_failed", drop_facts=True)
            return build()

    async def _draft(self, req, retailer, outcome: Outcome, facts: ResolvedFacts,
                     own: dict[str, Policy], started: float) -> str:
        others = await asyncio.to_thread(self.policies.other_retailers, retailer)
        own_texts = [p.text for p in own.values()]
        rules = RULES[retailer]
        allowed = {v for v in facts.values.values() if isinstance(v, int) and not isinstance(v, bool)}
        allowed |= {rules.return_window_days, rules.ship_investigation_min_overdue}
        if rules.damage_photo_window_days:
            allowed.add(rules.damage_photo_window_days)
        for t in own_texts + [outcome.draft]:
            allowed |= {int(n) for n in re.findall(r"\b\d+\b", t)}

        dreq = DraftRequest(
            retailer=retailer,
            decision=outcome.decision,
            reason=outcome.reason,
            approved_draft=outcome.draft,
            policy_excerpts=[c["excerpt"] for c in outcome.citations],
            facts={k: facts.values[k] for k in outcome.used_facts if k in facts.values},
            customer_message=req.message,
        )
        # Budget: per-attempt timeout x attempts (+ backoff), never past the request deadline.
        retries = max(0, min(self.settings.llm_max_retries, 2))
        budget = self.settings.llm_timeout_s * (1 + retries) + 0.6 * retries
        remaining = self.settings.request_budget_s - (time.perf_counter() - started)
        budget = min(budget, remaining)
        if budget <= 0:
            raise ModelError("timeout")
        try:
            text = await asyncio.wait_for(self.model.draft(dreq), timeout=budget)
        except asyncio.TimeoutError as exc:
            raise ModelError("timeout") from exc
        violations = validate_draft(
            text,
            retailer=retailer,
            other_retailer_policy_ids=[p.policy_id for p in others],
            other_retailer_texts=[p.text for p in others],
            own_texts=own_texts,
            allowed_numbers=allowed,
        )
        if violations:
            log.warning("model draft rejected: %s", violations)
            raise ModelError("unsafe_output")
        return text

    def _citations_verified(self, retailer: str, citations: list[dict]) -> bool:
        for c in citations:
            p = self.policies.get(retailer, c["policy_id"])
            if p is None or c["excerpt"] not in p.text:
                return False
        return True

    def _write_audit(self, r: TriageResponse, req: TriageRequest, erp_status: str, fallback_reason: str | None) -> None:
        try:
            self.audit.write(
                request_id=r.request_id,
                ticket_id=r.ticket_id,
                retailer=r.retailer,
                order_ref=req.order_ref,
                category=r.category,
                decision=r.decision,
                policy_ids=sorted({c.policy_id for c in r.citations}),
                erp_status=erp_status,
                discrepancies=r.discrepancies,
                missing_information=r.missing_information,
                model_provider=r.model.provider,
                model_used=r.model.used,
                fallback=r.model.fallback,
                fallback_reason=fallback_reason,
                latency_ms=r.latency_ms,
            )
        except Exception:
            # Availability over audit completeness for a single row; alerting on this log
            # line is part of the ops plan (docs/INCIDENTS.md).
            log.exception("audit write failed request_id=%s", r.request_id)
