# Design note

## Request path

`X-API-Key` → retailer (server-side map, constant-time compare) → **classify** (rules) →
**ERP lookup** (`ErpAdapter.get_order(order_ref, retailer)`, run in a thread under a wall-clock
timeout) → **reconcile** client hints against the ERP → **retrieve** the policy row
(`SELECT … FROM policy WHERE retailer = :r`, one query, then picked by category) → **decide** in code (`services/policy_service.py`) →
**draft** (the model rephrases an approved draft) → **validate** the draft and the verbatim
citations → **audit** one `triage_log` row → respond.

Routing precedence, where the first match wins: ERP timeout/error → fallback; unsupported or
`other` → human review; mixed issue → human review; no or unknown order → needs information;
client/ERP discrepancy → human review; otherwise the policy decision. A model failure, an unsafe
draft or a failed citation check after that point → fallback.

## Retrieval

The corpus is six short policies, each mapped one-to-one to `(retailer, category)`. Retrieval
is therefore a parameterised SQL lookup on those two columns. Embeddings or a vector DB
would add cost and nondeterminism and give no recall benefit here. The retailer predicate
sits inside the query (`PolicyRepository.for_retailer`). No code path loads another retailer's
policy for answering. The guardrail does read the other retailer's policy *IDs/texts*, but only
to detect leakage in a draft. Citations are whole policy sentences produced by splitting the
stored text, so they are verbatim by construction. They are re-checked against the DB before
responding, and any mismatch triggers the fallback. If this grew to hundreds of free-text
policies per retailer, I would add Postgres full-text search or `pgvector` under the same
retailer predicate. A vector index alone would not enforce isolation.

## Policy enforcement

Eligibility is decided only in `services/policy_service.py`. It is pure, deterministic and fully unit-tested
at every boundary (30/31, 14/15, 7/8, 5/6, 3/4, final sale at any day). Thresholds live in a
`RULES` table. `test_rule_thresholds_match_policy_text` parses the numbers out of the policy
wording ("within 30 days", "more than five days" → ≥ 6), so editing a policy text without
updating the rule (or the reverse) fails CI. Decisive negatives are checked before missing
facts, so a final-sale item is declined even if its condition is unknown. A delivered-but-late
order has `days_overdue = 0` per FIXTURES and never triggers the shipping policy. A return
request on an item the ERP marks `DAMAGED` follows the damaged-item policy and cites
"Damaged items follow the damaged-item policy."

`policy_supported` means the recommendation follows policy, and that can be a decline (for
example Cedar day 20). Nothing is executed. `next_action` always says what an agent should do,
and the response never claims a refund, replacement or return was approved.

## ERP integration and reconciliation

- `FlatFileErpAdapter` parses the pipe-delimited feed. It reads `DD-MM-YYYY` dates, turns
  `Y/N/blank` into `True/False/None`, and keeps blank or malformed fields as `None`, never guessed.
  Retailer isolation happens inside the adapter: a mismatched retailer returns `None`, which is
  indistinguishable from an unknown ref. A test asserts the two responses are identical.
- **Reconciliation rule:** the ERP is the system of record. Day counts and `final_sale` come
  only from the ERP. If the ERP lacks them, they are reported in `missing_information` and are
  never filled from client hints. `unused` comes from `item_condition`; only when that field is blank may the
  client hint be used, and it is labelled `client` in `fact_sources`. `photo_provided` is always
  `client`. A client hint that contradicts the ERP counts as a discrepancy. The cases are:
  `final_sale` or `unused` mismatch, a day count off by more than ±1 day, a claim of overdue on a
  delivered order, or a claim of delivery on an undelivered one. Any discrepancy routes to
  `human_review` with neither side trusted. *Assumption:* a client claim that the item is "unused"
  on an ERP final-sale item is treated as a returnability contradiction even when the client
  does not mention final sale (acceptance case 8).
- An unknown or other-retailer order → `needs_information` (ask for the order number) and **no
  order facts are used**, even if the client supplied some.
- A found record with blanks splits by who can supply the fact:
  - A missing **ERP-only** fact (`days_since_delivery`, `days_overdue`, `final_sale`) →
    `human_review` (`erp_incomplete`, with the gaps listed in `missing_information`). Asking the
    customer would loop, because client hints never fill those.
  - A missing **customer-suppliable** fact (`unused` when the condition is blank,
    `photo_provided`) → `needs_information`.
  - A record with neither delivery nor promised date counts as incomplete (delivery status
    unknown), not "not yet delivered".
  - `DAMAGED` does not imply "used". It routes to the damaged-item policy and is not compared
    with a client `unused` hint.
- Timeout or error → bounded fallback.

## Authentication

The API key is the only source of retailer identity. A `retailer` field in the body is
ignored, and customer text and `order_ref` prefixes are never consulted. Keys are compared with
`hmac.compare_digest`. Locally they come from the fixture map; in Azure they come from Key Vault
(see the Azure plan). Missing or invalid keys → 401. Pydantic enforces the body schema,
non-negative day counts, ID patterns and the message length (→ 422). The response model enforces
`customer_response ≤ 400` characters, and the guardrail enforces ≤ 3 sentences.

## Model use and fallback

The model never sees a decision it can change. It gets the approved draft, the cited excerpts,
the facts used, and the customer message (delimited and marked untrusted), and it must return
`{"customer_response": "…"}`. Parsing is strict. The output guardrail rejects drafts that:

- promise refunds, replacements or exceptions
- name the other retailer or its policy IDs or clauses
- contain numbers not grounded in facts, policy text or rule thresholds
- leak internals
- are longer than 3 sentences or 400 characters

A timeout (per-attempt, capped by an overall 20 s request deadline), transport error, 429/5xx (at
most 2 bounded retries, off by default; a `Retry-After` longer than 2 s is not waited), malformed output, unsafe output or a citation mismatch all produce the
**same bounded fallback**: `decision=human_review`, generic acknowledgement, **no citations**,
`next_action` naming the reason, `model.fallback=true`, and the audit row records `fallback_reason`.
ERP failures use the same shape with `model.used=false` and no facts. Any *unexpected* exception
(a provider SDK bug, or a pipeline bug) is caught as `model_error` / `internal_error`, still
returns 200 `human_review`, and is still audited. The fake provider returns
the approved draft verbatim, so the tests check plumbing and guardrails, not phrasing quality.

## Audit log

There is one row per request, written on every path, including fallbacks. The row stores IDs,
retailer, category, decision, cited policy IDs, ERP status, structured discrepancies
(field/value pairs only), missing facts, provider, model used, fallback and reason, latency, and
a UTC timestamp. **The customer message and the drafted reply are not stored.** They can contain
PII, and the audit's purpose (which policy drove which decision, and whether a fallback fired)
does not need them. If reply review were required, I would store the draft in a separate table
with shorter retention and tighter RBAC. A failed audit write is logged loudly but does not fail
the request. That is a deliberate availability choice; it is alertable, and I would revisit it if
audit completeness were a regulatory requirement.

## Classification choice and evidence

The baseline is a rule classifier (regex keywords, plus flags for *mixed* and *unsupported*).
Evaluation on 50 labelled tickets (26 dev used to write the rules, 24 holdout written as
paraphrases and **not** used for tuning):

- Rules (after adding negation handling, e.g. "not damaged", and a split between strong and
  weak unsupported topics, both prompted by review cases rather than the holdout): holdout accuracy 0.50, macro-F1 0.49. **Precision is 1.0 on every operational class.**
  Every error is a recall miss that falls to `other` and therefore to human review. The failure
  mode is safe: more agent work, never wrong advice.
- TF-IDF + logistic regression (dev → holdout): accuracy 0.71, macro-F1 0.69. It catches more
  paraphrases, but it misroutes *between* classes (shipping→damaged, other→returns), and those
  errors can produce confident wrong policy advice. 5-fold CV on all 50 examples: 0.50, so it is
  unstable at this data size.

**Judgment.** Conventional logic is sufficient, and preferable, for everything after
classification: day arithmetic, boundaries, isolation and reconciliation must be exact and
auditable. It is also good enough for explicit, keyword-rich tickets. The LLM's real value is
**recall on paraphrases** ("snapped clean off", "nothing has shown up", "rather not keep them")
and on ambiguity and mixed intent, which is where the rules miss 12 of 24 holdout cases. It also
adds value in drafting a natural reply. I did not wire an LLM classifier in, because I could not
evaluate one against a real model. Shipping it without measuring it would be the wrong call.

## Limitations

- No real-model run, so draft quality, real latency and LLM-classification value are unmeasured.
- The guardrail is heuristic (regex). The eval shows it missing promises phrased without
  trigger words (recall 0.875 on 22 drafts). A real model would need an additional check:
  an entailment check of the draft against the approved draft, or an LLM judge, with
  human sampling.
- The classifier holdout set is small (24) and I wrote it myself; the metrics have wide error bars.
- The ERP adapter has a single attempt, no circuit breaker, and re-reads the file per lookup
  (fine for the fixture, not for a real system).
- Human-review routing is an outcome only. There is no queue or hand-off integration.
- The static API-key map has no hashing, rotation or per-key rate limiting (pushed to APIM in the Azure plan).

## Next improvement

Add **LLM-assisted classification as a second stage, gated by the rule baseline**. When the
rules return `other` without an explicit unsupported topic, ask the model for exactly one label
from the enum plus a confidence score. Accept the label only if it parses and passes the confidence
threshold; otherwise keep `other`. Measure it with `eval/run_eval.py` against a larger holdout
on a real model. The target is holdout recall up with precision on operational classes no lower
than 0.95. I picked this because it addresses the largest measured weakness (12/24 holdout misses)
without touching the deterministic decision path.
