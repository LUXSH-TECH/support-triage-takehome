<!-- Paste into the pull request body (template from .github/PULL_REQUEST_TEMPLATE.md). Fill the blanks. -->

## Submission

- **Name:** Rohit <surname>
- **Time spent (approx):** <fill in>
- **Real model used?** no. All tests and evaluation use the deterministic fake provider. An OpenAI / Azure OpenAI provider is implemented and tested only against a mocked HTTP transport.
- **Where's the code?** this branch (`submission/rohit`)

## AI-assistant usage

<Describe honestly. For example: an AI assistant (Claude) generated the initial code, tests and docs. I reviewed each module, re-ran `pytest` and `python -m eval.run_eval`, checked every day-count boundary by hand against the README table, and changed …>

## How to run it

```bash
# setup
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# run the service
uvicorn app.main:app --port 8000

# run the tests
pytest -q

# run the evaluation (single command)
python -m eval.run_eval
```

## Checklist

- [x] Pinned dependency versions and a deterministic **fake model provider** are included.
- [x] Tests cover the acceptance cases, policy boundaries, auth/validation, retailer
      isolation, ERP failure modes, and prompt-injection attempts. (149 tests)
- [x] A single **evaluation command** runs and its **results** are included (with failures
      and classifier metrics), stating whether a real model was used. (`eval/results/latest.md`)
- [x] **Azure plan** + one architecture diagram + an illustrative config are included. (`docs/AZURE_PLAN.md`, `infra/`)
- [x] **Design note** covers retrieval, policy enforcement, ERP reconciliation, auth,
      fallback, limitations, and the next improvement. (`docs/DESIGN.md`)
- [x] **No credentials, real API keys, secrets, or personal data** are committed.
- [x] Incomplete work is documented honestly. (README → Submission notes)

## Notes for the reviewer

- The original assignment README moved to `docs/ASSIGNMENT.md`. Fixtures in `data/` and `erp/` are unchanged.
- ERP simulation: refs ending `-TIMEOUT` raise a timeout. Refs ending `-SLOW` are delayed, then resolve to the base ref.
- Reconciliation assumption: when the client says "unused" and the ERP says final sale, that counts as a discrepancy even if the client didn't state `final_sale` (acceptance case 8).
- An ERP record missing ERP-only facts goes to `human_review` (`erp_incomplete`) instead of asking the customer, because client hints never fill those facts.
- Known evaluation failures, kept on purpose:
  - own case `O1` (paraphrase): the rule classifier routes it to human review;
  - 2 of 22 detector drafts: promises phrased without trigger words.
