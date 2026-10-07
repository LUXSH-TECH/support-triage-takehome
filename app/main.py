"""FastAPI application: auth, /health, /triage."""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import Settings
from .db import AuditRepository, PolicyRepository, init_db, make_engine
from .erp import ErpAdapter, FlatFileErpAdapter
from .llm import ModelProvider, build_provider
from .policy_engine import RULES
from .schemas import TriageRequest, TriageResponse
from .service import TriageService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(
    settings: Settings | None = None,
    erp: ErpAdapter | None = None,
    model: ModelProvider | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        init_db(engine, settings.policies_seed)
        policies = PolicyRepository(engine)
        # Fail fast on misconfiguration: every retailer behind an API key must have rules
        # and policies, otherwise requests for it would error at runtime.
        unknown = set(settings.api_keys.values()) - (set(RULES) & policies.retailers())
        if unknown:
            raise RuntimeError(f"API keys map to retailers without rules/policies: {sorted(unknown)}")
        app.state.settings = settings
        app.state.policies = policies
        app.state.erp = erp or FlatFileErpAdapter(settings.erp_feed, settings.erp_slow_delay_s)
        app.state.service = TriageService(
            settings=settings,
            policies=policies,
            audit=AuditRepository(engine),
            erp=app.state.erp,
            model=model or build_provider(settings),
        )
        yield
        engine.dispose()

    app = FastAPI(title="Support Triage", version="1.0.0", lifespan=lifespan)

    def authenticate(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
        """Retailer identity comes from the API key only (constant-time comparison)."""
        if x_api_key:
            for key, retailer in settings.api_keys.items():
                if hmac.compare_digest(x_api_key.encode(), key.encode()):
                    return retailer
        raise HTTPException(status_code=401, detail="missing or invalid API key")

    @app.get("/health")
    def health(request: Request):
        state = request.app.state
        checks: dict[str, dict] = {}
        try:
            state.policies.ping()
            checks["policy_store"] = {"ok": True, "policies": state.policies.count()}
        except Exception:
            checks["policy_store"] = {"ok": False}
        try:
            checks["erp"] = {"ok": bool(state.erp.ping())}
        except Exception:
            checks["erp"] = {"ok": False}
        healthy = all(c["ok"] for c in checks.values())
        body = {"status": "ok" if healthy else "degraded", **checks}
        return JSONResponse(body, status_code=200 if healthy else 503)

    @app.post("/triage", response_model=TriageResponse)
    async def triage(body: TriageRequest, request: Request, retailer: str = Depends(authenticate)):
        return await request.app.state.service.triage(body, retailer)

    return app


app = create_app()
