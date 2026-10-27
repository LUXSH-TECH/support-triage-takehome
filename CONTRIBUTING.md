# Submitting your solution

Thanks for taking the time to work on this take-home. This document explains how to
submit your work and how to ask questions. It replaces a typical open-source
"contributing" guide — you are not contributing to this repo's assignment text, you are
submitting a solution built from it.

> **Before you start:** read [`README.md`](README.md) (the assignment) and
> [`FIXTURES.md`](FIXTURES.md) (the shared data, reference date, and test API keys).

## How to submit (pull request)

You do **not** need any access granted — submit from your own fork. You cannot push a
branch directly to this repository, and you don't need to.

1. **Fork** this repository (the **Fork** button, top-right).
2. In your fork, create a branch, e.g. `submission/<your-name>` (e.g. `submission/asha-r`).
3. Build your solution and push it to **your fork**. Keep the provided `data/` and `erp/`
   fixtures where they are, and note in your own README any fixture you changed.
4. Open a **pull request** from your fork into
   `LUXSH-TECH/support-triage-takehome:main`, and fill in the pull-request template.
5. Do **not** merge it yourself — opening the PR is the submission.

**Can't fork or open a PR?** No problem — share a link to your own Git repository (or a
ZIP) with your Luxsh contact instead. That's a perfectly fine fallback; a PR is just a
little easier for the review and live walkthrough.

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
