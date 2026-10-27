import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from app.classifier import classify
from app.config import Settings
from app.db import Policy, Repository
from app.engine import Outcome, decide, review
from app.erp import ErpClient
from app.facts import Resolved, derive_erp_facts, reconcile
from app.guards import mentions_other_retailer, suspicious, validate_draft
from app.llm import DraftContext, ModelProvider
from app.models import Citation, ModelInfo, TriageRequest, TriageResponse

log = logging.getLogger("triage")


def sentences(text: str) -> list[str]:
    return re.split(r"(?<=\.)\s+", text.strip())  # pieces of the original -> always verbatim substrings


class TriageService:
    def __init__(self, repo: Repository, erp: ErpClient, provider: ModelProvider, settings: Settings):
        self.repo, self.erp, self.provider, self.s = repo, erp, provider, settings
        self._pool = ThreadPoolExecutor(max_workers=16)  # bounds slow ERP/model calls with a timeout

    def _bounded(self, fn, timeout_s, *args):
        return self._pool.submit(fn, *args).result(timeout=timeout_s)

    def triage(self, retailer: str, req: TriageRequest) -> TriageResponse:
        t0 = time.perf_counter()
        category = classify(req.message)
        policy: Policy | None = None
        resolved = Resolved()
        erp_failed = False
        outcome: Outcome

        if suspicious(req.message) or mentions_other_retailer(req.message, retailer):
            outcome = review("Route to a human agent: message needs manual handling.")
        elif category == "other":
            outcome = decide("other", retailer, {})
        else:
            policy = self.repo.get_policy(retailer, category)  # scoped to the authenticated retailer
            record = None
            try:
                record = self._bounded(self.erp.get_order, self.s.erp_timeout_s, retailer, req.order_ref)
            except Exception:  # timeout, connection error, anything: never a 500 for a dependency
                log.exception("ERP lookup failed")
                erp_failed = True

            if policy is None:
                outcome = review("Route to a human agent: no policy available for this case.")
            elif erp_failed:
                outcome = review("ERP unavailable: route to a human agent. No order facts were verified.")
            elif record is None:  # unknown ref OR other retailer's ref: identical on purpose
                outcome = Outcome("needs_information", "Ask the customer to confirm a valid order reference.",
                                  "We couldn't find an order matching that reference. Could you double-check your order number?",
                                  missing=["order_ref"])
            else:
                erp_facts = derive_erp_facts(record, self.s.today)
                resolved = reconcile(category, req.facts, erp_facts)
                if resolved.discrepancies:
                    outcome = review("Client facts conflict with the order system: human review. Promise nothing.")
                else:
                    outcome = decide(category, retailer, resolved.values, erp_facts.damaged)

        # ---- drafting (model only polishes wording; it never decides) ----
        model_used, fallback = False, erp_failed
        reply = outcome.reply
        if outcome.decision != "human_review" and policy is not None:
            citations = self._citations(policy, outcome.cite)
            ctx = DraftContext(retailer, outcome.decision, outcome.next_action, outcome.reply,
                               tuple(c.excerpt for c in citations))
            model_used = True
            try:
                reply = validate_draft(self._bounded(self.provider.draft, self.s.model_timeout_s, ctx), retailer)
            except Exception:  # timeout, provider error, malformed/unsafe output
                log.exception("model draft failed -> fallback")
                fallback = True
                outcome = review("Automated drafting failed: route to a human agent.")
                reply = outcome.reply

        citations = self._citations(policy, outcome.cite) if policy and not fallback else []
        latency_ms = int((time.perf_counter() - t0) * 1000)
        request_id = str(uuid.uuid4())
        self.repo.log_triage(
            request_id=request_id, ticket_id=req.ticket_id, retailer=retailer, category=category,
            decision=outcome.decision, policy_ids=[c.policy_id for c in citations],
            model_provider=self.provider.name, fallback=fallback, latency_ms=latency_ms,
        )
        return TriageResponse(
            ticket_id=req.ticket_id, request_id=request_id, retailer=retailer, category=category,
            decision=outcome.decision, next_action=outcome.next_action, customer_response=reply,
            citations=citations, missing_information=outcome.missing, fact_sources=resolved.sources,
            discrepancies=resolved.discrepancies,
            model=ModelInfo(provider=self.provider.name, used=model_used, fallback=fallback),
            latency_ms=latency_ms,
        )

    @staticmethod
    def _citations(policy: Policy, idxs: list[int]) -> list[Citation]:
        parts = sentences(policy.text)
        return [Citation(policy_id=policy.policy_id, excerpt=parts[i]) for i in idxs]