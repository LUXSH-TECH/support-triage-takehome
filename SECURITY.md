# Security policy

This repository holds a hiring take-home assignment and its fixtures. It contains no
production systems and no real credentials.

## Reporting a vulnerability

If you find a genuine security problem — in the assignment materials here, or something you
believe exposes Luxsh systems or data — please report it **privately**. Do not open a
public issue or include exploit details in a pull request.

- Preferred: use GitHub's **private vulnerability reporting** on this repository
  (*Security → Report a vulnerability*), if enabled.
- Otherwise: email `hiran.harilal@luxshtech.com`, or your Luxsh hiring contact directly.

Please include what you found, where, and how to reproduce it. We will acknowledge and
respond as quickly as we reasonably can.

## Handling secrets in your submission

- **Never commit real credentials, API keys, tokens, connection strings, or personal
  data.** The keys in [`FIXTURES.md`](FIXTURES.md) (e.g. `test-key-northstar-001`) are
  fake, throwaway values used only for local development.
- A secret scan ([gitleaks](.gitleaks.toml)) runs against changes. If it flags something,
  fix it rather than bypassing the check.
- Keep any real model-provider key in an untracked `.env` (already covered by
  [`.gitignore`](.gitignore)); do not hard-code it.
