import hmac

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from app.config import Settings
from app.db import Repository
from app.erp import ErpClient, FileErp
from app.llm import ModelProvider, build_provider
from app.models import TriageRequest, TriageResponse
from app.service import TriageService


def create_app(settings: Settings | None = None, erp: ErpClient | None = None,
               provider: ModelProvider | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    repo = Repository(settings.db_path)
    repo.init(settings.schema_path, settings.policies_path)  # create tables + seed policies at startup
    erp = erp or FileErp(settings.erp_path)
    provider = provider or build_provider(settings.model_provider, settings.model_timeout_s)
    service = TriageService(repo, erp, provider, settings)

    app = FastAPI(title="Support Triage")

    def authenticate(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
        """Retailer identity comes from the API key ONLY."""
        if x_api_key:
            for key, retailer in settings.api_keys.items():
                if hmac.compare_digest(key.encode(), x_api_key.encode()):
                    return retailer
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    @app.get("/health")
    def health():
        store_ok, erp_ok = repo.ping(), erp.ping()
        body = {"status": "ok" if store_ok and erp_ok else "degraded",
                "policy_store": "ok" if store_ok else "unreachable",
                "erp": "ok" if erp_ok else "unreachable"}
        return JSONResponse(body, status_code=200 if store_ok and erp_ok else 503)

    @app.post("/triage", response_model=TriageResponse)
    def triage(req: TriageRequest, retailer: str = Depends(authenticate)):
        return service.triage(retailer, req)

    return app