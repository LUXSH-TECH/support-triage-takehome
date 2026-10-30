from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Request


def authenticated_retailer(
    request: Request, api_key: str | None = Header(default=None, alias="X-API-Key")
) -> str:
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    for configured_key, retailer in request.app.state.api_keys.items():
        if hmac.compare_digest(api_key, configured_key):
            return retailer
    raise HTTPException(status_code=401, detail="Invalid API key")