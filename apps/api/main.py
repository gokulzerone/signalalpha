"""SignalAlpha API (PRD §10). All endpoints live under ``/api/v1`` behind a single API key.
Every response carries ``as_of``, the dataset and a data-quality summary; mock and live data
are never mixed in one response."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from sqlalchemy import Engine

from apps.api.deps import require_api_key
from apps.api.routers import agents, companies, discovery, research, system
from apps.api.settings import ApiSettings, get_api_settings
from database.engine import get_engine, get_sessionmaker
from pipelines.dispatch import Dispatcher, build_dispatcher

DISCLAIMER = (
    "SignalAlpha presents research rankings derived from public information only. Outputs may "
    "contain errors, past signal performance is not indicative of future returns, and nothing "
    "here constitutes investment advice."
)


def create_app(
    engine: Engine | None = None,
    settings: ApiSettings | None = None,
    dispatcher: Dispatcher | None = None,
) -> FastAPI:
    app = FastAPI(title="SignalAlpha API", version="0.1.0", description=DISCLAIMER)
    app.state.settings = settings or get_api_settings()
    app.state.sessionmaker = get_sessionmaker(engine or get_engine())
    app.state.dispatcher = dispatcher or build_dispatcher(app.state.sessionmaker)

    api = FastAPI(
        dependencies=[Depends(require_api_key)], title="SignalAlpha API v1", description=DISCLAIMER
    )
    api.state = app.state
    api.include_router(companies.router)
    api.include_router(agents.router)
    api.include_router(discovery.router)
    api.include_router(research.router)
    api.include_router(system.router)

    @api.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "disclaimer": DISCLAIMER}

    app.mount("/api/v1", api)
    return app


def app() -> FastAPI:
    return create_app()
