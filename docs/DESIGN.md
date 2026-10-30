# Design Note

## Request path

FastAPI validates the request and maps `X-API-Key` to one of the two retailer identities.
That identity is passed explicitly to the ERP adapter, policy repository, response
validator, and audit writer. Classification is a small deterministic keyword baseline.
The service then looks up the order, derives facts against the fixture's fixed date,
reconciles client hints, retrieves one policy from SQLite, applies Python policy rules,
and drafts a short response through the model-provider interface. A successful or fallback
result gets one relational audit row.

## Isolation and policy enforcement

The policy repository's SQL predicate includes both authenticated `retailer` and category;
the policy ID query also includes retailer. It never loads all retailers' policies and
filters in application code. The ERP adapter indexes records by `(retailer, order_ref)`,
so a cross-retailer reference returns the same `None` result as an unknown reference.
Customer-provided retailer values are rejected by request validation.

Return windows, final-sale rejection, damage-photo timing, and shipping-investigation
thresholds are deterministic rules in `app/domain/decisions.py`, not instructions to a
model. The model receives only the authenticated retailer, the message as untrusted text,
one selected policy, verified facts, missing fields, and reconciliation status. The fake
provider does not interpret the ticket; it renders the already-approved next action.
This boundary keeps authorization testable and prevents prompt injection from changing
policy or tenant scope. An LLM can be useful for paraphrase handling and concise drafting,
but it is not a reliable authority for eligibility or customer/order facts.

## ERP reconciliation and missing data

Dates are parsed from the supplied pipe-delimited feed. A delivered order has
`days_overdue = 0`; an undelivered order derives overdue days from its promised date.
`UNUSED` and `USED` map to a known boolean; `DAMAGED` does not establish whether an item
was unused. For each client hint with a corresponding ERP value, a mismatch is recorded
and routes to `human_review`; the ERP value remains authoritative. If an authoritative
ERP field is blank, a client value is ignored and the field is listed as missing when
needed for the decision. `photo_provided` has no ERP counterpart, so it can only be a
client-provided hint. No missing ERP fact is guessed.

## Classification, grounding, and fallback

The classifier is a readable rule baseline. It recognizes multiple issue groups and
routes mixed or unrecognized requests to review. The labeled evaluation set reports
per-category precision, recall, F1, and a confusion matrix; those metrics are in-sample
checks of this fixed baseline, not evidence of generalization.

The fake provider is deterministic, offline, and credential-free. No real model provider
is configured. Draft validation caps output at three sentences and 400 characters,
rejects unsafe refund/replacement promises, cross-retailer mentions, unverified numeric
day claims, unscoped citations, and excerpts that are not exact stored-policy substrings.
It does not retry. ERP timeout yields `human_review`; missing or incomplete records request
information or review; model timeout or invalid output yields `human_review` with a
generic response and no citation. Every business outcome and fallback is audited.

## Authentication, audit, and limitations

Local fixture keys are server-side configuration; production keys must be rotated and
stored in a secret manager. Authentication failures return the same 401 response. Health
output contains only dependency reachability. Logs omit API keys, messages, and order
references. Audit data stores request/ticket IDs, retailer, category, decision, cited
policy IDs, provider, fallback, latency, and UTC creation time; the customer message is
not persisted.

SQLite and SQLAlchemy keep local operation simple and the repository query layer portable
to a managed relational database. Local startup creates schema and seeds fixture policies;
production should use reviewed, versioned migrations. The keyword classifier has no
semantic understanding, and only the fake provider is tested. ERP failure simulation is
suffix-based (`-TIMEOUT`, `-SLOW`) rather than a real network timeout. The next improvement
would be a shadow-mode evaluation against a labeled, representative support dataset,
including human-reviewed ambiguity and classifier calibration, before enabling a real
model for drafting.