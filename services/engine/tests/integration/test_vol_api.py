"""API de volatilidade e eventos com as fixtures reais (PRD §7, §10.1 API)."""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_vol_recompute import _collect, _recompute
from vollab.analytics.recompute import JOB_KIND
from vollab.db.models import CorporateAction, Job

pytestmark = pytest.mark.integration


@pytest.fixture
def loaded(
    make_session: sessionmaker[Session], tmp_path: Path, fixture_settings: None, api_client: TestClient
) -> Iterator[TestClient]:
    with make_session() as s:
        _collect(s, tmp_path)
        _recompute(s)
    yield api_client


def test_read_endpoints(loaded: TestClient) -> None:
    c = loaded
    summary = c.get("/underlyings/PETR4/summary").json()
    assert summary["as_of"] == "2026-11-19"
    assert summary["expected_as_of"] == "2026-11-19"
    assert summary["intraday"]["complete"] is True
    q = summary["iv_quality"]
    assert q["trades_synced"] + q["trades_lag_discarded"] == q["trades_valid"]

    prices = c.get("/underlyings/PETR4/prices", params={"days": 30}).json()
    assert len(prices["points"]) == 30
    assert len(prices["calendar"]) >= 30

    series = c.get("/underlyings/PETR4/series").json()
    assert series["as_of"] == "2026-11-19"
    with_iv = [x for x in series["series"] if x["iv"] is not None]
    assert with_iv and all(x["iv"]["origin"] == "estimated" for x in with_iv)

    rv = c.get("/underlyings/PETR4/vol/realized").json()
    assert rv["official_close_to_close"] == "close_to_close"
    names = {(e["estimator"], e["window_bd"]) for e in rv["estimators"]}
    assert ("yang_zhang", 20) in names and ("intraday_5m", 60) in names
    intraday = next(e for e in rv["estimators"] if e["estimator"] == "intraday_5m" and e["window_bd"] == 20)
    # 11 pregões intradiários < 20: dados insuficientes, sem número e com motivo.
    assert intraday["latest"]["status"] == "insufficient_data"
    assert intraday["latest"]["value"] is None
    assert intraday["latest"]["reason"]
    c2c = next(e for e in rv["estimators"] if e["estimator"] == "close_to_close" and e["window_bd"] == 20)
    assert c2c["latest"]["status"] == "ok" and 0 < c2c["latest"]["value"] < 2

    smile = c.get("/underlyings/PETR4/vol/implied/smile").json()
    assert smile["expiry"] == "2026-12-18"
    assert smile["points"] and all(0.05 < p["iv"] < 3 for p in smile["points"])
    assert smile["atm_iv"]["status"] == "ok"

    term = c.get("/underlyings/PETR4/vol/term-structure").json()
    assert term["as_of"] == "2026-11-19"
    assert [p["atm_iv"]["status"] for p in term["points"]] == ["ok", "unavailable"]

    cm = c.get("/underlyings/PETR4/vol/constant-maturity").json()
    latest = cm["latest"]
    # Só um vencimento com ATM: prazo constante indisponível; ATM do vencimento disponível e prazo efetivo.
    assert latest["iv"]["status"] == "unavailable" and latest["iv"]["value"] is None
    assert latest["fallback_expiry"] == "2026-12-18" and latest["fallback_bd"] == 20

    assert c.get("/underlyings/XXXX3/vol/realized").status_code == 404


def test_events_crud_dividend_and_jumps(loaded: TestClient, make_session: sessionmaker[Session]) -> None:
    c = loaded
    # Validações (422) do Pydantic e da regra de negócio.
    assert (
        c.post(
            "/events",
            json={
                "kind": "ex_dividend",
                "ticker": "PETR4",
                "event_date": "2026-12-01",
                "status": "estimated",
            },
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/events", json={"kind": "earnings", "event_date": "2026-12-01", "status": "estimated"}
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/events",
            json={"kind": "earnings", "ticker": "ZZZZ3", "event_date": "2026-12-01", "status": "estimated"},
        ).status_code
        == 422
    )

    div = c.post(
        "/events",
        json={
            "kind": "ex_dividend",
            "ticker": "PETR4",
            "event_date": "2026-12-01",
            "status": "confirmed",
            "amount": "0.85",
        },
    )
    assert div.status_code == 201, div.text
    div_id = div.json()["id"]
    with make_session() as s:
        action = s.scalar(select(CorporateAction).where(CorporateAction.event_id == div_id))
        assert action is not None and action.source == "manual" and action.kind == "dividend"
        jobs = s.scalars(select(Job).where(Job.kind == JOB_KIND).order_by(Job.id.desc())).first()
        assert jobs is not None and jobs.payload["tickers"] == ["PETR4"] and jobs.payload["full"] is True

    patched = c.patch(f"/events/{div_id}", json={"amount": "0.90", "event_date": "2026-12-02"})
    assert patched.status_code == 200 and patched.json()["amount"] == "0.900000"
    with make_session() as s:
        action = s.scalar(select(CorporateAction).where(CorporateAction.event_id == div_id))
        assert action is not None and action.ex_date == date(2026, 12, 2)

    # Resultado passado (gap de 26/10) e um futuro.
    past = c.post(
        "/events",
        json={"kind": "earnings", "ticker": "PETR4", "event_date": "2026-10-26", "status": "confirmed"},
    )
    future = c.post(
        "/events",
        json={"kind": "earnings", "ticker": "PETR4", "event_date": "2026-12-10", "status": "estimated"},
    )
    assert past.status_code == 201 and future.status_code == 201
    copom = c.post("/events", json={"kind": "copom", "event_date": "2026-12-09", "status": "confirmed"})
    assert copom.status_code == 201

    listed = c.get("/events", params={"ticker": "PETR4"}).json()
    kinds = {e["kind"] for e in listed}
    assert {"ex_dividend", "earnings", "copom", "expiry"} <= kinds
    assert all(e["derived"] == (e["id"] is None) for e in listed)

    jumps = c.get("/underlyings/PETR4/event-jumps").json()
    assert jumps["as_of"] == "2026-11-19"
    (jump,) = jumps["jumps"]
    assert jump["event"]["event_date"] == "2026-12-10"
    # Só um vencimento com ATM: sem estimativa pela estrutura a termo; o histórico tem 1 resultado.
    assert jump["term_structure_value"] is None and jump["term_structure_reason"]
    assert jump["historical_n"] == 1
    assert jump["jump"]["origin"] == "approximate"
    assert jump["jump"]["value"] == pytest.approx(jump["historical_value"])
    assert jump["jump"]["ci_low"] <= jump["jump"]["value"] <= jump["jump"]["ci_high"]

    cm = c.get("/underlyings/PETR4/vol/constant-maturity").json()["latest"]
    assert cm["iv_ex_event"]["status"] == "unavailable"

    assert c.delete(f"/events/{div_id}").status_code == 204
    assert c.delete(f"/events/{div_id}").status_code == 404
    with make_session() as s:
        assert s.scalar(select(CorporateAction).where(CorporateAction.event_id == div_id)) is None
