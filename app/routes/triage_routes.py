"""POST /triage — check the API key, then hand the ticket to triage_service."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..schemas import TriageRequest, TriageResponse
from ..services.auth_service import get_retailer_for_key
from ..services.triage_service import run_triage

router = APIRouter()


def current_retailer(request: Request, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    """Retailer comes from the API key only — never from the body or the message."""
    retailer = get_retailer_for_key(x_api_key, request.app.state.ctx.settings.api_keys)
    if retailer is None:
        raise HTTPException(status_code=401, detail="missing or invalid API key")
    return retailer


@router.post("/triage", response_model=TriageResponse)
async def triage(body: TriageRequest, request: Request, retailer: str = Depends(current_retailer)):
    return await run_triage(body, retailer, request.app.state.ctx)
