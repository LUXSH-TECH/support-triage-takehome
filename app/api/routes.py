from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.domain.models import TriageRequest, TriageResponse
from app.api.dependencies import authenticated_retailer


router = APIRouter()


@router.get("/health")
def health(request: Request) -> dict[str, object]:
    try:
        policy_store = request.app.state.database.health_check()
    except Exception:
        policy_store = False
    try:
        erp_reachable = request.app.state.erp.health_check()
    except Exception:
        erp_reachable = False
    return {
        "status": "ok" if policy_store and erp_reachable else "degraded",
        "policy_store": policy_store,
        "erp": erp_reachable,
    }


@router.post("/triage", response_model=TriageResponse)
def triage(
    body: TriageRequest,
    request: Request,
    retailer: str = Depends(authenticated_retailer),
) -> TriageResponse:
    return request.app.state.triage_service.triage(body, retailer)