"""Contrato da coleta e dos ativos (PRD §7) com Postgres de teste e fontes simuladas."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from vollab.collection.runner import run_collection_job
from vollab.db.models import CollectionRun

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("fixture_settings")]


def test_pending_before_first_collection(api_client: TestClient) -> None:
    body = api_client.get("/collection/pending").json()
    assert body["reference_date"] == "2026-11-19"
    assert body["is_initial_load"] is True
    assert body["data_source"] == "fixtures"
    counts = {c["group"]: c["count"] for c in body["counts"]}
    # 63 pregões × (1 COTAHIST + 3 ativos) e o OHLC de 1 ano (anuais 2025 e 2026).
    assert counts["cotahist_daily"] == 63
    assert counts["underlying_trades"] == 63 * 3
    assert counts["cotahist_annual"] == 2
    assert counts["option_trades"] == 0  # só se sabe depois do COTAHIST de cada pregão
    assert body["days_awaiting_cotahist"] == 63
    assert body["pending_days"][-1] == "2026-11-19" and len(body["pending_days"]) == 63
    assert body["estimated_seconds"] == body["known_requests"]  # 1 req/s
    assert body["active_run"] is None


def test_run_lifecycle_progress_and_gaps(api_client: TestClient, session: Session) -> None:
    created = api_client.post("/collection/runs")
    assert created.status_code == 202
    run_id = created.json()["run"]["id"]
    assert created.json()["run"]["status"] == "queued"
    assert api_client.post("/collection/runs").status_code == 409
    assert api_client.get("/collection/pending").json()["active_run"]["id"] == run_id

    run_collection_job(session, {"run_id": run_id})  # o que o worker faria

    progress = api_client.get(f"/collection/runs/{run_id}").json()
    assert progress["run"]["status"] == "partial"
    assert progress["current"] is None
    totals = progress["totals"]
    assert totals["pending"] == 0
    assert totals["total"] == totals["ok"] + totals["empty"] + totals["failed"]
    groups = {g["group"]: g for g in progress["groups"]}
    assert groups["option_trades"]["ok"] > 0

    gaps = api_client.get("/collection/gaps").json()
    kinds = {s["kind"]: s["count"] for s in gaps["summary"]}
    # Fixtures só têm PETR4 intradiário e o COTAHIST de 17-19/11: o resto é lacuna reportada.
    assert kinds["underlying_trades_failed"] >= 63 * 2
    assert "r4_diverged" not in kinds
    petr_19 = [g for g in gaps["gaps"] if g["underlying"] == "PETR4" and g["trade_date"] == "2026-11-19"]
    assert {g["kind"] for g in petr_19} <= {"options_failed"}
    assert gaps["failures_total"] >= len(gaps["failures"]) > 0

    health = api_client.get("/health").json()
    assert health["last_collection_at"] is not None
    pending = api_client.get("/collection/pending").json()
    assert pending["is_initial_load"] is False
    assert pending["last_run"]["id"] == run_id
    # O que já foi gravado não volta; só itens com falha não permanente.
    counts = {c["group"]: c["count"] for c in pending["counts"]}
    assert counts["cotahist_daily"] == 60  # 17-19/11 resolvidos
    assert counts["underlying_trades"] == 0  # 404 de ticker = definitivo


def test_unknown_run_is_404(api_client: TestClient) -> None:
    response = api_client.get("/collection/runs/999999")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


def test_orphan_active_run_does_not_block_new_runs(api_client: TestClient, session: Session) -> None:
    run_id = api_client.post("/collection/runs").json()["run"]["id"]
    run = session.get(CollectionRun, run_id)
    assert run is not None
    session.execute(text("UPDATE collection_runs SET status = 'running' WHERE id = :id"), {"id": run_id})
    session.execute(text("UPDATE jobs SET status = 'failed' WHERE id = :id"), {"id": run.job_id})
    session.commit()
    again = api_client.post("/collection/runs")
    assert again.status_code == 202
    session.refresh(run)
    assert run.status == "failed"


def test_underlyings_crud_and_limit(api_client: TestClient) -> None:
    listed = api_client.get("/underlyings").json()
    assert [u["ticker"] for u in listed] == ["BBAS3", "BOVA11", "PETR4"]
    assert api_client.post("/underlyings", json={"ticker": "petr4"}).status_code == 422
    assert api_client.post("/underlyings", json={"ticker": "PETR4"}).status_code == 409
    for ticker in ("VALE3", "ITUB4", "BBDC4", "MGLU3", "PRIO3", "B3SA3", "BEEF3"):
        created = api_client.post("/underlyings", json={"ticker": ticker})
        assert created.status_code == 201
        assert created.json() == {"ticker": ticker, "isin": None, "active": True}
    assert api_client.post("/underlyings", json={"ticker": "WEGE3"}).status_code == 409  # 11º ativo
    assert api_client.patch("/underlyings/BEEF3", json={"active": False}).json()["active"] is False
    assert api_client.post("/underlyings", json={"ticker": "WEGE3"}).status_code == 201
    assert api_client.patch("/underlyings/BEEF3", json={"active": True}).status_code == 409
    assert api_client.patch("/underlyings/XXXX3", json={"active": True}).status_code == 404


def test_new_underlying_gets_isin_from_cotahist(api_client: TestClient, session: Session) -> None:
    api_client.post("/underlyings", json={"ticker": "VALE3"})
    run_id = api_client.post("/collection/runs").json()["run"]["id"]
    run_collection_job(session, {"run_id": run_id})
    vale = next(u for u in api_client.get("/underlyings").json() if u["ticker"] == "VALE3")
    assert vale["isin"] == "BRVALEACNOR0"
