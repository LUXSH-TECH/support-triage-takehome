"""App entry point: start-up (DB + seed), shared context, and the routes.

Run:  uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings
from .context import AppContext
from .database import AuditRepository, PolicyRepository, init_db, make_engine
from .routes import health_routes, triage_routes
from .services.erp_service import ErpAdapter, FlatFileErpAdapter
from .services.llm_service import ModelProvider, build_provider
from .services.policy_service import RULES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(settings: Settings | None = None, erp: ErpAdapter | None = None, model: ModelProvider | None = None) -> FastAPI:
    """`erp` and `model` can be swapped in tests (e.g. a fake ERP or a failing model)."""
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 1. Create tables and load data/policies.json into the database
        engine = make_engine(settings.database_url)
        init_db(engine, settings.policies_seed)
        policies = PolicyRepository(engine)

        # 2. Fail fast if an API key points to a retailer we have no rules/policies for
        unknown = set(settings.api_keys.values()) - (set(RULES) & policies.retailers())
        if unknown:
            raise RuntimeError(f"API keys map to retailers without rules/policies: {sorted(unknown)}")

        # 3. Shared objects every request uses
        app.state.ctx = AppContext(
            settings=settings,
            policies=policies,
            audit=AuditRepository(engine),
            erp=erp or FlatFileErpAdapter(settings.erp_feed, settings.erp_slow_delay_s),
            model=model or build_provider(settings),
        )
        yield
        engine.dispose()

    app = FastAPI(title="Support Triage", version="1.0.0", lifespan=lifespan)
    app.include_router(health_routes.router)
    app.include_router(triage_routes.router)
    return app


app = create_app()
