from __future__ import annotations

from fastapi.testclient import TestClient


def test_data_quality_and_performance(client: TestClient, mock_backtest: int) -> None:
    dq = client.get("/api/v1/data-quality").json()["data"]
    assert dq and all(row["source"] for row in dq) and all(row["ticker"] for row in dq)
    perf = client.get("/api/v1/signals/performance", params={"as_of": "2026-08-31"}).json()["data"]
    assert perf["backtest_run_id"] == mock_backtest
    rows = perf["rows"]
    assert rows and {r["horizon_days"] for r in rows} == {30, 90, 180, 365}
    order_win = [r for r in rows if r["subject"] == "order_win" and r["horizon_days"] == 180]
    assert order_win and "mean_excess" in order_win[0]["stats"] and "decay" in order_win[0]["stats"]
    assert all(isinstance(r["low_sample"], bool) for r in rows)
    before = client.get("/api/v1/signals/performance", params={"as_of": "2023-01-01"}).json()[
        "data"
    ]
    assert before["backtest_run_id"] is None and before["rows"] == []
    sp = client.get("/api/v1/scores/performance", params={"as_of": "2026-08-31"}).json()["data"]
    assert sp["backtest_run_id"] == mock_backtest


def test_platform_liveness_needs_no_key(secured_client: TestClient) -> None:
    assert secured_client.get("/health").json() == {"status": "ok"}
    assert secured_client.get("/api/v1/health").status_code == 401
