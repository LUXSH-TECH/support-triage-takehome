# Fixtures

Shared inputs for the take-home. Every candidate starts from the same data, so submissions
are comparable. Do not edit these files except where the assignment invites you to reshape
the ERP feed into your own local store; note any change in your submission.

## Contents

| Path | What it is |
| --- | --- |
| [`data/policies.json`](data/policies.json) | The six retailer policies. Load into your relational store. Cited excerpts must match this text **verbatim**. |
| [`data/schema.sql`](data/schema.sql) | Reference relational schema (`policy` + `triage_log`). Adapt as you like. |
| [`erp/orders.psv`](erp/orders.psv) | The simulated **legacy ERP** feed. |

## Fixed reference date

Derive day counts against a **fixed "today" of 2025-09-01** (pass it in; do not use the
system clock) so tests are deterministic.

- `days_since_delivery = today − delivery_date`, and applies only once the item has been
  delivered (a non-blank `delivery_date`).
- `days_overdue` applies **only to shipments that have not yet been delivered** (a blank
  `delivery_date`): `days_overdue = today − promised_date`. For an order that has already
  been delivered, treat `days_overdue` as `0` — a late-but-delivered shipment is history,
  not an open carrier investigation, and must not trigger the shipping policy.

## Test API keys → retailer

Map these server-side. Retailer identity comes from the key only. These are throwaway test
values for local development, not secrets.

```
X-API-Key: test-key-northstar-001   ->  northstar
X-API-Key: test-key-cedar-002       ->  cedar
```

## ERP feed notes (`erp/orders.psv`)

Columns: `order_ref | retailer | order_date | delivery_date | promised_date | final_sale | item_condition | channel`

- Dates are `DD-MM-YYYY`. Blank fields are genuinely missing — do not invent them.
- `final_sale` is `Y`/`N`/blank. `item_condition` is `UNUSED`/`USED`/`DAMAGED`/blank.
- The feed contains records for **both retailers**, covering returns, damaged items,
  shipping delays, final-sale items, and deliberately incomplete records. Inspect the file.
- A record whose `retailer` differs from the authenticated retailer must be treated as
  **not found** (isolation at the data layer).
- **Simulated failures (suggested convention, so your tests stay deterministic):** make your
  ERP adapter raise a timeout for any `order_ref` ending in `-TIMEOUT`, and return a delayed
  but valid record for one ending in `-SLOW`. Document whatever convention you choose.

You author your own labelled classification set (≥ 20 examples) and your own four
evaluation cases, as described in the assignment.
