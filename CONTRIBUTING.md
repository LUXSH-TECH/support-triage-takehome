# Submitting your solution

Thanks for taking the time to work on this take-home. This document explains how to
submit your work and how to ask questions. It replaces a typical open-source
"contributing" guide — you are not contributing to this repo's assignment text, you are
submitting a solution built from it.

> **Before you start:** read [`README.md`](README.md) (the assignment) and
> [`FIXTURES.md`](FIXTURES.md) (the shared data, reference date, and test API keys).

## How to submit (pull request)

We review submissions as a pull request against this repository.

1. You will be granted push access to a working branch, or added as a collaborator. If you
   have not been, tell your Luxsh contact and we will sort it out.
2. Create a branch named `submission/<your-name>` (e.g. `submission/asha-r`).
3. Build your solution on that branch. Keep the provided `data/` and `erp/` fixtures where
   they are, and note in your own README any fixture you changed.
4. Open a **pull request into `main`** and fill in the pull-request template completely.
5. Do **not** review or merge your own PR — opening it is the submission.

**Can't push here?** If access can't be arranged in time, you may instead submit a link to
your own Git repository (or a ZIP) in a pull request description or by email to your Luxsh
contact. A PR is preferred because it makes the review and the live walkthrough easier.

## What to include

Mirror the submission checklist in the assignment:

- Source code with **pinned dependency versions** and a deterministic **fake model provider**.
- Your automated tests and evaluation cases, plus a single runnable evaluation command.
- Your own **README** with exact setup, run, test, and evaluation commands.
- Example requests/responses and evaluation results (including failures and classifier
  metrics), and whether a real model was used.
- The Azure plan, one architecture diagram, and an illustrative configuration.
- A short design note (retrieval, policy enforcement, ERP reconciliation, authentication,
  fallback, limitations, next improvement).
- Time spent, incomplete work, and how you used AI assistants.

## Ground rules

- **Never commit credentials, real API keys, secrets, or personal data.** The test keys in
  [`FIXTURES.md`](FIXTURES.md) are fake, throwaway values. A secret scan runs on every push.
- Timebox to roughly eight hours of build time. Unfinished work described honestly scores
  better than half-working extras.
- Keep the git history yours — small, clear commits are welcome; we do not require any
  particular commit style.

## Asking questions

Open an **Issue** using the *Assignment question* form (see
[Issues](../../issues/new/choose)). Ambiguity is expected in places — if a decision is
yours to make, state your assumption in your design note and proceed.
