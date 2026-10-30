"""API key -> retailer. The ONLY place retailer identity comes from."""

from __future__ import annotations

import hmac


def get_retailer_for_key(api_key: str | None, api_keys: dict[str, str]) -> str | None:
    """Return the retailer for a valid key, else None. Constant-time comparison."""
    if not api_key:
        return None
    for key, retailer in api_keys.items():
        if hmac.compare_digest(api_key.encode(), key.encode()):
            return retailer
    return None
