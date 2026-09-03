from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from apps.api.main import create_app
from apps.api.settings import ApiSettings
from data.mock.generator import GenerationReport


@pytest.fixture
def client(mock_engine: Engine, mock_universe: GenerationReport) -> Iterator[TestClient]:
    app = create_app(mock_engine, ApiSettings(api_key=None, default_dataset="mock"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def secured_client(mock_engine: Engine, mock_universe: GenerationReport) -> Iterator[TestClient]:
    app = create_app(mock_engine, ApiSettings(api_key="secret", default_dataset="mock"))
    with TestClient(app) as c:
        yield c
