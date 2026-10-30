# Support Triage — solution

A small FastAPI service that classifies a support ticket, looks the order up in a simulated
legacy ERP, retrieves the authenticated retailer's policy from a relational store, decides in
code, and drafts a grounded reply. The original assignment text is in
[`docs/ASSIGNMENT.md`](docs/ASSIGNMENT.md) (moved from `README.md`, otherwise unchanged).

| Document | Contents |
| --- | --- |
| [`docs/DESIGN.md`](docs/DESIGN.md) | Design note: retrieval, policy enforcement, ERP reconciliation, auth, fallback, classifier choice, limitations, next improvement |
| [`docs/AZURE_PLAN.md`](docs/AZURE_PLAN.md) | Azure architecture (diagram), identity, deployment/rollback, scaling, cost |
| [`docs/INCIDENTS.md`](docs/INCIDENTS.md) | Incident runbooks A–D |
| [`eval/results/latest.md`](eval/results/latest.md) | Evaluation results (incl. failures and classifier metrics) |
| [`docs/EXAMPLES.md`](docs/EXAMPLES.md) | Example requests/responses |
| [`infra/`](infra/) | Illustrative Bicep + GitHub Actions workflow (**untested**, placeholders labelled) |

**Real model used: no.** Every test and every result in this repo uses the deterministic fake
provider. An OpenAI / Azure OpenAI provider is implemented and unit-tested against a mocked
HTTP transport only; no real-model quality or latency is claimed.

## Setup

Requires Python 3.12+ (tested on 3.13). The versions in `requirements.txt` are fully pinned.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --port 8000        # fake provider by default
curl -s localhost:8000/health
curl -s localhost:8000/triage -H 'X-API-Key: test-key-northstar-001' -H 'Content-Type: application/json' \
  -d '{"ticket_id":"T-1001","order_ref":"NS-88231","message":"The jacket does not fit, I would like to send it back."}'
```

The SQLite file `triage.db` is created (git-ignored) and policies are seeded from
`data/policies.json` at startup (idempotent upsert). Inspect the audit log with
`sqlite3 triage.db 'select * from triage_log'`.

## Test and evaluate

```bash
pytest -q                     # 149 tests, offline, fake provider, ~5 s
python -m eval.run_eval       # single evaluation command -> eval/results/latest.{md,json}
```

## Configuration

All via environment variables (template: [`.env.example`](.env.example); load with `set -a; source .env; set +a`). Defaults run fully offline.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./triage.db` | SQLAlchemy URL (e.g. `postgresql+psycopg://…` in Azure) |
| `REFERENCE_DATE` | `2025-09-01` | Fixed "today" for day arithmetic (never the system clock) |
| `ERP_FEED` | `erp/orders.psv` | Legacy feed path |
| `ERP_TIMEOUT_S` / `ERP_SLOW_DELAY_S` | `2.0` / `0.3` | Service-side ERP timeout / simulated `-SLOW` delay |
| `LLM_PROVIDER` | `fake` | `fake` \| `openai` \| `azure_openai` |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` | `8` / `0` | Per-attempt timeout; retries hard-capped at 2; `Retry-After` > 2 s is not waited |
| `REQUEST_BUDGET_S` | `20` | Overall deadline; the model call never runs past it |
| `FAKE_LLM_MODE` | `ok` | `ok` \| `timeout` \| `malformed` \| `unsafe` (simulate failures) |
| `API_KEYS_JSON` | fixture keys | `{"<key>": "<retailer>"}`; in Azure supplied from Key Vault |

### Pointing at a real model

```bash
# OpenAI-compatible endpoint
export LLM_PROVIDER=openai LLM_MODEL=<model> LLM_API_KEY=<key>   # LLM_BASE_URL optional
# or Azure OpenAI
export LLM_PROVIDER=azure_openai LLM_BASE_URL=https://<resource>.openai.azure.com \
       LLM_AZURE_DEPLOYMENT=<deployment> LLM_API_KEY=<key>
python -m eval.run_eval      # now reports real-model p50/p95 over N=20 (EVAL_LATENCY_N to raise)
```

Keys go in an untracked `.env`/shell only. The model only rephrases an approved draft; its
output is validated and any failure returns the bounded `human_review` fallback.

## ERP simulation convention

| `order_ref` | Behaviour |
| --- | --- |
| ends in `-TIMEOUT` | Adapter raises a timeout → bounded fallback (`human_review`, no facts) |
| ends in `-SLOW` | Sleeps `ERP_SLOW_DELAY_S`, then returns the record for the base ref (e.g. `NS-88231-SLOW`). If the delay exceeds `ERP_TIMEOUT_S`, the service's own timeout fires. |
| other retailer's ref | Treated exactly like an unknown ref (`needs_information`, no disclosure) |
| any ref | Matched case-insensitively (`ns-88231` = `NS-88231`) |

Fixtures in `data/` and `erp/` are **unchanged**. Tests add synthetic in-memory ERP records
for day-count boundaries (`tests/conftest.py::order`).

## Layout

```
app/
  main.py                    starts the app: DB + policy seed, shared context, includes routes
  config.py                  settings from environment variables
  context.py                 AppContext: the shared objects (settings, DB repos, ERP, model)
  database.py                tables (policy, triage_log), seed loader, repositories
  schemas.py                 request / response models (validation)
  routes/
    health_routes.py         GET  /health
    triage_routes.py         POST /triage  -> checks API key -> services.triage_service.run_triage()
  services/
    triage_service.py        the flow, step 1..8 (start reading here)
    auth_service.py          API key -> retailer
    classifier_service.py    message -> returns | damaged_item | shipping | other
    erp_service.py           legacy ERP adapter + lookup_order() with timeout
    facts_service.py         ERP facts + customer facts -> reconciled facts, discrepancies
    policy_service.py        choose_outcome(): the decision rules, thresholds, citations
    llm_service.py           fake / real model + draft_customer_reply()
    guardrail_service.py     checks the model's reply (no promises, no other retailer, ...)
    audit_service.py         save_audit_log(): one triage_log row per request
eval/                        cases.json, classifier_dataset.jsonl, run_eval.py, results/
tests/                       pytest suite
docs/  infra/  scripts/
```

### How one request flows

```
POST /triage
  └─ routes/triage_routes.py      current_retailer()  -> auth_service.get_retailer_for_key()  (401 if bad)
       └─ services/triage_service.py   run_triage()
            1. classifier_service.classify(message)
            2. erp_service.lookup_order(order_ref, retailer)        timeout/error -> fallback
            3. facts_service.resolve_facts(order, client_facts)     ERP wins, conflicts recorded
            4. database: policies.for_retailer(retailer)            only this retailer's policies
            5. policy_service.choose_outcome(...)                    decision + citations (in code)
            6. llm_service.draft_customer_reply(...)                 model rewrites, guardrail checks
            7. verify citations are exact quotes of stored policy text
            8. audit_service.save_audit_log(...)                     always, even on fallback
```

## Evaluation summary (fake provider)

From [`eval/results/latest.md`](eval/results/latest.md):

- End-to-end cases: **19/20 pass**. Citations verbatim 20/20, retailer-isolation violations 0,
  unsupported claims in responses 0. The one failure is my own paraphrase case `O1`
  ("the base had snapped clean off"): the rule classifier returns `other`, so the ticket
  goes to `human_review` instead of `policy_supported`. It fails safe, but it still counts as a failure.
- Unsupported-claim detector: 22 labelled drafts, recall 0.875 / precision 1.0. It misses two
  promises phrased without trigger words ("we'll sort out a new one", "let this one slide").
  The detector is a regex heuristic, so these misses are expected and reported, not hidden.
- Rule classifier: dev 1.00 accuracy (the rules were written against this split, so this is
  not a fair number), **holdout 0.50 accuracy / macro-F1 0.49**. Precision is 1.0 on every
  operational class and recall is low. Errors all fall to `other`, which routes to human review.
  TF-IDF + LR scores 0.71 holdout accuracy but misroutes real tickets between classes. Discussion is in the design note.

## Submission notes

- **Time spent:** approximately 7 hours.
- **AI-assistant usage:** I used Claude to draft the service code, tests, evaluation script, Azure plan,
  incident runbooks and design note. I checked its output by running all 149 tests and
  `python -m eval.run_eval` myself, sending real requests to the running service with curl, and
  confirming that `data/` and `erp/` are identical to the provided fixtures. All results use the
  fake model only.
- **Incomplete / not done:** no real-model evaluation (no access). No LLM-assisted
  classification, which is proposed but not built. The Azure assets are illustrative and were
  never deployed. ERP adapter retries and a circuit breaker are not implemented (one attempt,
  then fallback). The API keys are a static map, with no key hashing or rotation endpoint.
