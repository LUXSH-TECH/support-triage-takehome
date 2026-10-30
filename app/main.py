from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.routes import router
from app.config import ROOT, Settings, get_settings
from app.database import Database
from app.erp.mock_erp import MockERP
from app.model.fake import FakeModelProvider
from app.model.interface import ModelProvider
from app.repositories.audit_repository import AuditRepository
from app.repositories.policy_repository import PolicyRepository
from app.services.triage_service import TriageService


def create_app(
    settings: Settings | None = None,
    *,
    database_url: str | None = None,
    erp: MockERP | None = None,
    model_provider: ModelProvider | None = None,
) -> FastAPI:
    configuration = settings or get_settings()
    if database_url is not None:
        configuration = Settings(
            database_url=database_url,
            northstar_api_key=configuration.northstar_api_key,
            cedar_api_key=configuration.cedar_api_key,
            today=configuration.today,
            erp_path=configuration.erp_path,
            fake_model_mode=configuration.fake_model_mode,
        )

    database = Database(configuration.database_url)
    erp_adapter = erp or MockERP(configuration.erp_path)
    provider = model_provider or FakeModelProvider(configuration.fake_model_mode)
    policy_repository = PolicyRepository(database)
    audit_repository = AuditRepository(database)
    service = TriageService(
        erp=erp_adapter,
        policies=policy_repository,
        audit=audit_repository,
        model_provider=provider,
        today=configuration.today,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.initialize(ROOT / "data" / "policies.json")
        yield
        database.engine.dispose()

    application = FastAPI(title="Support Triage", version="1.0.0", lifespan=lifespan)
    application.state.database = database
    application.state.erp = erp_adapter
    application.state.policy_repository = policy_repository
    application.state.triage_service = service
    application.state.api_keys = {
        configuration.northstar_api_key: "northstar",
        configuration.cedar_api_key: "cedar",
    }
    application.include_router(router)
    return application


app = create_app()