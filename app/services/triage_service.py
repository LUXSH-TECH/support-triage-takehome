from __future__ import annotations

import logging
import time
import uuid
from datetime import date

from app.classifier.baseline import classify
from app.domain.decisions import PolicyOutcome, decide
from app.domain.models import Citation, TriageRequest, TriageResponse
from app.erp.interface import ERPClient
from app.model.interface import ModelContext, ModelProvider
from app.model.validation import InvalidDraft, validate_draft
from app.repositories.audit_repository import AuditRepository
from app.repositories.policy_repository import Policy, PolicyRepository
from app.services.reconciliation import reconcile


logger = logging.getLogger(__name__)


class TriageService:
    def __init__(
        self,
        *,
        erp: ERPClient,
        policies: PolicyRepository,
        audit: AuditRepository,
        model_provider: ModelProvider,
        today: date,
    ) -> None:
        self.erp = erp
        self.policies = policies
        self.audit = audit
        self.model_provider = model_provider
        self.today = today

    def triage(self, request: TriageRequest, retailer: str) -> TriageResponse:
        started = time.perf_counter()
        request_id = str(uuid.uuid4())
        classification = classify(request.message)
        category = classification.category
        policy = self.policies.get(retailer, category) if category != "other" else None
        client_facts = request.facts.model_dump(exclude_none=True)

        try:
            order = self.erp.get_order(retailer, request.order_ref)
        except Exception as error:
            logger.warning(
                "ERP lookup failed request_id=%s error_type=%s",
                request_id,
                type(error).__name__,
            )
            return self._finish(
                request=request,
                request_id=request_id,
                retailer=retailer,
                category=category,
                decision="human_review",
                next_action="A support specialist must review this request because order details could not be verified.",
                facts={},
                fact_sources={},
                missing_information=[],
                discrepancies=[],
                policy=None,
                citation_excerpt=None,
                fallback=True,
                model_used=False,
                started=started,
            )

        if classification.mixed or classification.ambiguous:
            outcome = PolicyOutcome("human_review", "A support specialist must review this request.")
            reconciliation = None
        elif order is None and retailer == "cedar" and category == "damaged_item" and policy:
            outcome = PolicyOutcome(
                "human_review",
                "A support specialist must review this damaged-item complaint; no refund or replacement is promised.",
                citation_excerpt=policy.text,
            )
            reconciliation = None
        elif order is None:
            return self._finish(
                request=request,
                request_id=request_id,
                retailer=retailer,
                category=category,
                decision="needs_information",
                next_action="Please verify the order reference so support can check the order details.",
                facts={},
                fact_sources={},
                missing_information=["order_ref"],
                discrepancies=[],
                policy=None,
                citation_excerpt=None,
                fallback=False,
                model_used=True,
                started=started,
            )
        else:
            reconciliation = reconcile(order.facts(self.today), client_facts)
            if reconciliation.discrepancies:
                outcome = PolicyOutcome(
                    "human_review", "A support specialist must review conflicting order information.",
                    citation_sentence_index=1 if category == "returns" else 0,
                )
            else:
                outcome = decide(retailer, category, reconciliation.facts, policy)

        facts = reconciliation.facts if reconciliation is not None else {}
        fact_sources = reconciliation.fact_sources if reconciliation is not None else {}
        discrepancies = reconciliation.discrepancies if reconciliation is not None else []
        citation_excerpt = None
        if policy is not None and outcome.citation_excerpt is not None:
            citation_excerpt = outcome.citation_excerpt
        elif policy is not None:
            citation_excerpt = self.policies.citation_excerpt(
                policy, outcome.citation_sentence_index
            )

        missing_information = list(outcome.missing_information)
        if classification.mixed:
            missing_information = []

        return self._finish(
            request=request,
            request_id=request_id,
            retailer=retailer,
            category=category,
            decision=outcome.decision,
            next_action=outcome.next_action,
            facts=facts,
            fact_sources=fact_sources,
            missing_information=missing_information,
            discrepancies=discrepancies,
            policy=policy,
            citation_excerpt=citation_excerpt,
            fallback=False,
            model_used=True,
            started=started,
        )

    def _finish(
        self,
        *,
        request: TriageRequest,
        request_id: str,
        retailer: str,
        category: str,
        decision: str,
        next_action: str,
        facts: dict[str, object],
        fact_sources: dict[str, str],
        missing_information: list[str],
        discrepancies: list[dict[str, object]],
        policy: Policy | None,
        citation_excerpt: str | None,
        fallback: bool,
        model_used: bool,
        started: float,
    ) -> TriageResponse:
        provider_name = getattr(self.model_provider, "name", "unknown")
        citations: list[Citation] = []
        customer_response = next_action

        if model_used and not fallback:
            context = ModelContext(
                retailer=retailer,
                ticket_message=request.message,
                category=category,
                decision=decision,
                next_action=next_action,
                policy_id=policy.policy_id if policy else None,
                policy_text=policy.text if policy else None,
                citation_excerpt=citation_excerpt,
                verified_facts=facts,
                missing_information=tuple(missing_information),
                has_discrepancies=bool(discrepancies),
            )
            try:
                draft = self.model_provider.draft(context)
                expected_citation = (
                    (policy.policy_id, citation_excerpt)
                    if policy is not None and citation_excerpt is not None
                    else None
                )
                validated = validate_draft(
                    draft,
                    retailer,
                    policy,
                    facts,
                    expected_response=next_action,
                    expected_citation=expected_citation,
                )
                customer_response = validated.response
                citations = [Citation(**citation.__dict__) for citation in validated.citations]
            except (Exception, InvalidDraft) as error:
                logger.warning(
                    "Model draft rejected request_id=%s error_type=%s",
                    request_id,
                    type(error).__name__,
                )
                fallback = True
                decision = "human_review"
                next_action = "A support specialist must review this request because a grounded response could not be validated."
                customer_response = "A support specialist must review this request."
                citations = []

        latency_ms = max(0, int((time.perf_counter() - started) * 1000))
        self.audit.write(
            request_id=request_id,
            ticket_id=request.ticket_id,
            retailer=retailer,
            category=category,
            decision=decision,
            policy_ids=[citation.policy_id for citation in citations],
            model_provider=provider_name,
            fallback=fallback,
            latency_ms=latency_ms,
        )
        return TriageResponse(
            ticket_id=request.ticket_id,
            request_id=request_id,
            retailer=retailer,
            category=category,
            decision=decision,  # type: ignore[arg-type]
            next_action=next_action,
            customer_response=customer_response,
            citations=citations,
            missing_information=missing_information,
            fact_sources=fact_sources,  # type: ignore[arg-type]
            discrepancies=discrepancies,
            model={"provider": provider_name, "used": model_used, "fallback": fallback},
            latency_ms=latency_ms,
        )