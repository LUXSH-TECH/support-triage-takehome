# Support Triage Service

A local FastAPI service that triages customer support tickets for two retailers
(Northstar and Cedar). It classifies the ticket, looks up the order in a simulated
legacy ERP, retrieves the retailer's policy from a relational store, and returns an
evidence-backed decision with verbatim policy citations. Nothing is executed:
`policy_supported` means the recommendation follows policy.

## Quick start

Requires Python 3.12+ (developed and tested on 3.13).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:create_app --factory --port 8000
```

Health check: `curl localhost:8000/health`

Example request:

```bash
curl -X POST http://127.0.0.1:8000/triage \
  -H "X-API-Key: test-key-northstar-001" \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"T-1001","order_ref":"NS-88231","message":"The jacket does not fit, I would like to send it back."}'
```

Example response (abridged):

```json
{
  "ticket_id": "T-1001",
  "retailer": "northstar",
  "category": "returns",
  "decision": "policy_supported",
  "next_action": "Return is within policy: confirm eligibility and send return instructions.",
  "customer_response": "Based on our policy, your item appears eligible for return. A team member will confirm the next steps.",
  "citations": [{"policy_id": "N-RET", "excerpt": "Unused items may be returned within 30 days of delivery."}],
  "missing_information": [],
  "fact_sources": {"days_since_delivery": "erp", "final_sale": "erp", "unused": "erp"},
  "discrepancies": [],
  "model": {"provider": "fake", "used": true, "fallback": false}
}
```

## Tests and evaluation

Run both from the project root:

```bash
python -m pytest -q            # 59 passed (fake provider only)
python -m tests.run_eval       # the single evaluation command
```

### What the tests cover
- Acceptance cases from the assignment (return windows, damage with no photo,
  overdue shipment, cross-retailer request, missing info, warranty, client-vs-ERP
  conflict, other retailer's order, ERP timeout, model timeout/malformed output).
- Exact day-count edges (30/31, 14/15, 7/8, overdue 5/6 and 3/4, final sale at any age).
- Authentication (401), validation (422), retailer taken from the API key only.
- Client-vs-ERP reconciliation and ERP failure modes.
- Audit-log writes, including on the fallback path.
- Prompt-injection attempts and verbatim citations.

### Evaluation results (fake provider)

Rule baseline classifier, n=32 labelled examples (includes paraphrases, hard
cases and mixed issues):

| category | precision | recall | F1 | support |
|---|---|---|---|---|
| returns | 1.00 | 0.75 | 0.86 | 8 |
| damaged_item | 1.00 | 0.57 | 0.73 | 7 |
| shipping | 1.00 | 0.71 | 0.83 | 7 |
| other | 0.59 | 1.00 | 0.74 | 10 |

Accuracy 0.78.

Confusion matrix (rows = true, columns = predicted):

| | returns | damaged_item | shipping | other |
|---|---|---|---|---|
| returns | 6 | 0 | 0 | 2 |
| damaged_item | 0 | 4 | 0 | 3 |
| shipping | 0 | 0 | 5 | 2 |
| other | 0 | 0 | 0 | 10 |

All 7 misses (every one is a keyword-free paraphrase that falls into `other`,
which routes to human review):

- "Is it possible to take this back to the store? I no longer want it" (returns)
- "I don't want the sofa anymore" (returns)
- "There is a dent on the side of the fridge" (damaged_item)
- "The mug came in pieces" (damaged_item)
- "The stitching came apart on day one" (damaged_item)
- "It was supposed to be here last Monday" (shipping)
- "Any news on when my stuff gets delivered?" (shipping)

End-to-end cases: 15/15 passed (n=15; 8 verbatim-citation checks, 23 isolation
checks, 15 unsupported-claim checks, 0 failures). This includes my 4 own cases:
a paraphrase, an ambiguous request, a mixed issue and a prompt injection.

### Where an LLM adds value, and where rules are enough
- Rules are enough for keyword-rich tickets: precision is 1.00 for the three real
  categories, and errors fail safe into `other` (human review).
- The baseline's weakness is **recall on paraphrases** (all 7 misses). That is where
  an LLM, or a TF-IDF + logistic regression model, should help.
- **This is an expectation, not a measurement.** I did not evaluate a real model.

### What is automated vs human judgment
- Automated: everything above (tests, classifier metrics, end-to-end checks).
- Human judgment: the labels in the classifier set, the choice of own test cases,
  and whether the reply wording is good. No human evaluation of wording was done.
- All results use the **fake provider**. They show the plumbing is correct, **not**
  model quality. No p50/p95 latency is reported because no real model was called.

## Model provider

The default is a deterministic fake provider (no credentials needed).
An optional OpenAI-compatible provider is included, but **I did not run it
against a real endpoint**:

```bash
MODEL_PROVIDER=http LLM_BASE_URL=<url> LLM_MODEL=<model> LLM_API_KEY=<key> \
  uvicorn app.main:create_app --factory
```

Keep any real key in an untracked `.env` (already in `.gitignore`).

## API summary

| Situation | Status |
|---|---|
| Success | 200 |
| Missing/invalid `X-API-Key` | 401 |
| Malformed body, negative `days_since_delivery`/`days_overdue` | 422 |
| Unknown order, ERP timeout, model failure | 200 with `human_review` or `needs_information` |

`GET /health` reports whether the policy store and ERP adapter are reachable
(503 if either is not).

## Design summary

(Full explanation in `docs/design-note.md`.)

- **Code decides, the model only words.** Policy boundaries live in `app/engine.py`.
  The model gets only the structured decision, never the customer's message, and its
  output is validated (length, sentence count, promises, other retailer's names).
- **Retailer isolation at the data layer.** Retailer comes from the API key only.
  The SQL query has `WHERE retailer = ?`, and the ERP index is keyed by
  `(retailer, order_ref)`, so another retailer's order is "not found" and looks
  identical to an unknown order.
- **ERP is the system of record.** ERP values win. A differing client value is
  recorded as a discrepancy and the ticket goes to human review. The client can
  only fill facts the ERP leaves blank (labelled `"client"` in `fact_sources`).
- **Day arithmetic:** delivery day is day zero. `days_overdue` applies only to
  undelivered orders; a delivered order always has `days_overdue = 0`.
- **Fallback:** ERP failure, model timeout or malformed/unsafe model output gives a
  `human_review` result with no citations and no invented facts. `fallback` is
  `true` in these cases and the audit row is still written.
- **Audit log:** one row per request in `triage_log`. The customer message is
  never stored.
- **Citations** are sentences sliced from the stored policy text, so they are
  verbatim by construction.

## ERP simulation

Source: `erp/orders.psv`. Order refs ending in `-TIMEOUT` raise a timeout; refs
ending in `-SLOW` return a delayed but valid record.
Fixtures in `data/` and `erp/` are [unchanged / changed: describe].

## Limitations and unfinished work

- [Not done: scikit-learn classifier comparison (optional in the assignment).]
- Day-count mismatches between client and ERP are compared exactly, with no tolerance.
- The injection, other-retailer and "promise" checks are coarse regexes.
- No retries or circuit breaker around the ERP or model calls; a timed-out worker
  thread cannot be killed.
- SQLite is used locally; the repository class isolates SQL for a later move to
  Postgres/Azure SQL, but that move was not tested.
- The real-model provider is untested.
- [Azure plan status: done / partly done: describe.]

## Azure plan

`docs/azure-plan.md` (design only, nothing deployed or tested on Azure).
