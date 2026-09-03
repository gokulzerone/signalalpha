"""SignalAlpha API (PRD §10). Endpoints are added step by step; step 3 provides evidence and
document viewing, step 7 the rest."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from sqlalchemy import Engine

from apps.api.deps import require_api_key
from apps.api.routers import documents
from apps.api.settings import ApiSettings, get_api_settings
from database.engine import get_engine, get_sessionmaker

DISCLAIMER = (
    "SignalAlpha presents research rankings derived from public information only. Outputs may "
    "contain errors, past signal performance is not indicative of future returns, and nothing "
    "here constitutes investment advice or a recommendation."
)


def create_app(engine: Engine | None = None, settings: ApiSettings | None = None) -> FastAPI:
    app = FastAPI(title="SignalAlpha API", version="0.1.0", description=DISCLAIMER)
    app.state.settings = settings or get_api_settings()
    app.state.sessionmaker = get_sessionmaker(engine or get_engine())

    api = FastAPI(dependencies=[Depends(require_api_key)])
    api.state = app.state
    api.include_router(documents.router)

    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "disclaimer": DISCLAIMER}

    app.mount("/api/v1", api)
    return app


def app() -> FastAPI:
    return create_app()
