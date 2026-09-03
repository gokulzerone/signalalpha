from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from data.mock.synth import Story, load_blueprints
from database.models import Company


def _id(session: Session, story: Story) -> int:
    ticker = next(b.ticker for b in load_blueprints() if b.story is story)
    return session.scalars(select(Company.id).where(Company.ticker == ticker)).one()


def _wait(client: TestClient, run_id: str, timeout: float = 120) -> dict[str, object]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/runs/{run_id}").json()["data"]
        if body["status"] in ("completed", "failed"):
            return body  # type: ignore[no-any-return]
        time.sleep(0.5)
    raise AssertionError("run did not finish")


def test_research_job_runs_signals_and_scores(
    client: TestClient, mock_signals: int, mock_session: Session
) -> None:
    cid = _id(mock_session, Story.CONTROL)
    r = client.post(f"/api/v1/research/{cid}", params={"as_of": "2026-08-31"})
    assert r.status_code == 202, r.text
    run = r.json()["data"]
    assert run["status"] == "queued" and run["kind"] == "research"
    done = _wait(client, run["id"])
    assert done["status"] == "completed", done
    steps = done["steps"]
    assert isinstance(steps, list)
    names = [s["name"] for s in steps]
    assert names == ["refresh", "signals", "agents", "scores"]


def test_agent_job_validates_name(client: TestClient, mock_session: Session) -> None:
    cid = _id(mock_session, Story.CONTROL)
    assert client.post(f"/api/v1/agents/hidden_signal/{cid}").status_code == 404
    r = client.post(f"/api/v1/agents/financial/{cid}", params={"as_of": "2026-08-31"})
    assert r.status_code == 202
    done = _wait(client, r.json()["data"]["id"])
    assert done["status"] == "completed" and done["kind"] == "agent:financial"
    assert client.get("/api/v1/runs/does-not-exist").status_code == 404
