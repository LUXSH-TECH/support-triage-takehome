# Evaluation results

- Command: `python -m eval.run_eval`
- Model provider: **fake** — real model used: **no**. All model behaviour below is the deterministic fake provider; it proves plumbing and guardrails, **not model quality**.
- Reference date: 2025-09-01

## 1. End-to-end cases (automated checks)

| metric | passed / total |
|---|---|
| category | 19 / 20 |
| decision | 19 / 20 |
| policy_selection | 19 / 20 |
| citations_verbatim | 20 / 20 |
| no_isolation_violation | 20 / 20 |
| no_unsupported_claims | 20 / 20 |
| cases_passed | 19 / 20 |
| citations checked verbatim | 12 |

| case | source | result | failed checks | category | decision | cited |
|---|---|---|---|---|---|---|
| A1-ns-return-20d | acceptance | PASS | — | returns | policy_supported | N-RET |
| A2-cd-return-20d | acceptance | PASS | — | returns | policy_supported | C-RET |
| A3-ns-damaged-3d-no-photo | acceptance | PASS | — | damaged_item | needs_information | N-DMG |
| A4-ns-ship-6d-overdue | acceptance | PASS | — | shipping | policy_supported | N-SHIP |
| A5-cd-asks-ns-policies | acceptance | PASS | — | other | human_review | — |
| A6-return-no-facts-no-erp | acceptance | PASS | — | returns | needs_information | — |
| A7-warranty-extension | acceptance | PASS | — | other | human_review | — |
| A8-client-unused-erp-final-sale | acceptance | PASS | — | returns | human_review | N-RET |
| A9-other-retailer-order | acceptance | PASS | — | returns | needs_information | — |
| A10-erp-timeout | acceptance | PASS | — | returns | human_review | — |
| A11a-model-timeout | acceptance | PASS | — | returns | human_review | — |
| A11b-model-malformed | acceptance | PASS | — | returns | human_review | — |
| O1-paraphrase-damage | own | **FAIL** | category, decision, policy_selection | other | human_review | — |
| O2-ambiguous | own | PASS | — | other | human_review | — |
| O3-mixed-late-and-damaged | own | PASS | — | damaged_item | human_review | — |
| O4-cedar-used-on-day-14 | own | PASS | — | returns | policy_supported | C-RET |
| O5-final-sale-day-30 | own | PASS | — | returns | policy_supported | N-RET |
| O6-injection | own | PASS | — | returns | policy_supported | C-RET |
| O7-ns-ship-11d-slow-erp | own | PASS | — | shipping | policy_supported | N-SHIP |
| O8-ns-damaged-day-84 | own | PASS | — | damaged_item | human_review | N-DMG |

### Failures (1)

- **O1-paraphrase-damage** — failed ['category', 'decision', 'policy_selection']; expected `{'category': 'damaged_item', 'decision': 'policy_supported', 'policy_ids': ['N-DMG']}`, got category=`other`, decision=`human_review`. Note: Paraphrase with no stock damage keyword ('snapped'). Expected to expose the rule baseline.

## 2. Unsupported-claim detector (labelled drafts)

n=22 · TP=14 FP=0 FN=2 TN=6 · recall=0.875 precision=1.0

- miss: `Don't worry, we'll sort out a new one for you right away.` expected_flag=True flags=[]
- miss: `Since you are a loyal customer we can let this one slide.` expected_flag=True flags=[]

## 3. Classifier

#### Rule baseline — dev (n=26) — accuracy 1.0, macro-F1 1.0

| category | precision | recall | F1 | support |
|---|---|---|---|---|
| returns | 1.0 | 1.0 | 1.0 | 7 |
| damaged_item | 1.0 | 1.0 | 1.0 | 7 |
| shipping | 1.0 | 1.0 | 1.0 | 6 |
| other | 1.0 | 1.0 | 1.0 | 6 |

Confusion matrix (rows = true, cols = predicted):

| true \ pred | returns | damaged_item | shipping | other |
|---|---|---|---|---|
| returns | 7 | 0 | 0 | 0 |
| damaged_item | 0 | 7 | 0 | 0 |
| shipping | 0 | 0 | 6 | 0 |
| other | 0 | 0 | 0 | 6 |

#### Rule baseline — holdout (n=24) — accuracy 0.5, macro-F1 0.488

| category | precision | recall | F1 | support |
|---|---|---|---|---|
| returns | 1.0 | 0.167 | 0.286 | 6 |
| damaged_item | 1.0 | 0.5 | 0.667 | 6 |
| shipping | 1.0 | 0.333 | 0.5 | 6 |
| other | 0.333 | 1.0 | 0.5 | 6 |

Confusion matrix (rows = true, cols = predicted):

| true \ pred | returns | damaged_item | shipping | other |
|---|---|---|---|---|
| returns | 1 | 0 | 0 | 5 |
| damaged_item | 0 | 3 | 0 | 3 |
| shipping | 0 | 0 | 2 | 4 |
| other | 0 | 0 | 0 | 6 |

#### Rule baseline — all (n=50) — accuracy 0.76, macro-F1 0.775

| category | precision | recall | F1 | support |
|---|---|---|---|---|
| returns | 1.0 | 0.615 | 0.762 | 13 |
| damaged_item | 1.0 | 0.769 | 0.87 | 13 |
| shipping | 1.0 | 0.667 | 0.8 | 12 |
| other | 0.5 | 1.0 | 0.667 | 12 |

Confusion matrix (rows = true, cols = predicted):

| true \ pred | returns | damaged_item | shipping | other |
|---|---|---|---|---|
| returns | 8 | 0 | 0 | 5 |
| damaged_item | 0 | 10 | 0 | 3 |
| shipping | 0 | 0 | 8 | 4 |
| other | 0 | 0 | 0 | 12 |

#### TF-IDF + logistic regression — trained on dev, tested on holdout (n=24) — accuracy 0.708, macro-F1 0.687

| category | precision | recall | F1 | support |
|---|---|---|---|---|
| returns | 0.857 | 1.0 | 0.923 | 6 |
| damaged_item | 0.625 | 0.833 | 0.714 | 6 |
| shipping | 0.667 | 0.667 | 0.667 | 6 |
| other | 0.667 | 0.333 | 0.444 | 6 |

Confusion matrix (rows = true, cols = predicted):

| true \ pred | returns | damaged_item | shipping | other |
|---|---|---|---|---|
| returns | 6 | 0 | 0 | 0 |
| damaged_item | 0 | 5 | 0 | 1 |
| shipping | 0 | 2 | 4 | 0 |
| other | 1 | 1 | 2 | 2 |

#### TF-IDF + logistic regression — 5-fold stratified CV on all (n=50) — accuracy 0.5, macro-F1 0.463

| category | precision | recall | F1 | support |
|---|---|---|---|---|
| returns | 0.533 | 0.615 | 0.571 | 13 |
| damaged_item | 0.526 | 0.769 | 0.625 | 13 |
| shipping | 0.6 | 0.5 | 0.545 | 12 |
| other | 0.167 | 0.083 | 0.111 | 12 |

Confusion matrix (rows = true, cols = predicted):

| true \ pred | returns | damaged_item | shipping | other |
|---|---|---|---|---|
| returns | 8 | 2 | 1 | 2 |
| damaged_item | 1 | 10 | 1 | 1 |
| shipping | 1 | 3 | 6 | 2 |
| other | 5 | 4 | 2 | 1 |

#### Rule-baseline misclassifications (all splits)

| split | text | true | predicted |
|---|---|---|---|
| holdout | This coat is not what I expected, how do I go about sending it back to you? | returns | other |
| holdout | Bought this as a gift but they already have one. Can I get a refund for it? | returns | other |
| holdout | The trousers are way too long for me, I'd rather not keep them. | returns | other |
| holdout | Is it possible to swap these for a size up? | returns | other |
| holdout | Unopened, still has tags, want to give it back. | returns | other |
| holdout | The parcel showed up looking like it had been run over and the mirror inside is in bits. | damaged_item | other |
| holdout | The handle snapped off the first time I used it. | damaged_item | other |
| holdout | Box was soaked and the book pages are ruined. | damaged_item | other |
| holdout | It's been two weeks past the expected date and nothing has shown up. | shipping | other |
| holdout | Was supposed to get my order last Monday, still nothing. | shipping | other |
| holdout | Any update on when my stuff will actually get here? | shipping | other |
| holdout | The courier says delivered but I never got anything. | shipping | other |

## 4. Latency

provider=fake · real model: no · N=20 · p50=4.6 ms · p95=10.7 ms · fallbacks=0

_Fake provider: this is in-process plumbing latency (TestClient, SQLite, flat-file ERP), not model latency. No real-model latency is claimed._
