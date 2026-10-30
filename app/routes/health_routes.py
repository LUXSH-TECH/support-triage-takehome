"""GET /health — is the database and the ERP reachable? (no secrets in the output)"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
def health(request: Request):
    ctx = request.app.state.ctx
    checks = {}

    try:
        ctx.policies.ping()
        checks["policy_store"] = {"ok": True, "policies": ctx.policies.count()}
    except Exception:
        checks["policy_store"] = {"ok": False}

    try:
        checks["erp"] = {"ok": bool(ctx.erp.ping())}
    except Exception:
        checks["erp"] = {"ok": False}

    healthy = all(c["ok"] for c in checks.values())
    body = {"status": "ok" if healthy else "degraded", **checks}
    return JSONResponse(body, status_code=200 if healthy else 503)
