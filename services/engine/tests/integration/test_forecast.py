"""Previsão de RV e avaliação de modelos com as fixtures reais (PRD 1.7 §5.7, §7; T-REF-09, CS-03).

Fixtures: 221 pregões de OHLC oficial (02/01 a 19/11/2026) → 220 retornos; horizonte 21 du →
10 origens não sobrepostas. EWMA (mín. 60 retornos) chega a 7 janelas (< 8: dados insuficientes);
combinação e RV C2C 20 a 9; GARCH (mín. 240 retornos) a nenhuma; IV de prazo constante só existe
nos pregões com opções coletadas (nenhuma origem).
"""

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from tests.integration.test_vol_recompute import _collect, _recompute
from vollab.analytics.forecasting import JOB_KIND, run_forecast_job
from vollab.db.models import (
    DailyBar,
    ForecastEvaluation,
    ForecastEvaluationPoint,
    Job,
    RealizedVol,
    RvForecast,
)

pytestmark = pytest.mark.integration

LAST = date(2026, 11, 19)
TICKERS = ("BBAS3", "BOVA11", "PETR4")


def _forecast(session: Session) -> None:
    job = session.scalars(select(Job).where(Job.kind == JOB_KIND).order_by(Job.id.desc())).first()
    assert job is not None, "o recálculo de vol deve enfileirar a previsão"
    run_forecast_job(session, dict(job.payload))


@pytest.fixture
def forecasted(session: Session, tmp_path: Path) -> Session:
    _collect(session, tmp_path)
    _recompute(session)
    _forecast(session)
    return session


def _state(session: Session) -> dict[str, object]:
    return {
        name: session.execute(text(sql)).all()
        for name, sql in {
            "f": "SELECT ticker, as_of, model, horizon_bd, vol, ci_low, ci_high, status FROM rv_forecasts "
            "ORDER BY 1, 2, 3, 4",
            "e": "SELECT ticker, model, horizon_bd, n_windows, rmse, ratios::text FROM forecast_evaluations "
            "ORDER BY 1, 2, 3",
            "p": "SELECT ticker, model, origin, forecast, realized FROM forecast_evaluation_points "
            "ORDER BY 1, 2, 3",
        }.items()
    }


def test_evaluation_windows_never_share_a_day(forecasted: Session) -> None:
    """T-REF-09 sobre o que foi gravado: janelas (origem, fim] disjuntas, h pregões cada, ancoradas
    no último pregão, as mesmas origens para todos os modelos."""
    s = forecasted
    for ticker in TICKERS:
        days = list(
            s.scalars(
                select(DailyBar.trade_date).where(DailyBar.ticker == ticker).order_by(DailyBar.trade_date)
            )
        )
        index = {d: i for i, d in enumerate(days)}
        origins_by_model: dict[str, list[date]] = {}
        for p in s.scalars(
            select(ForecastEvaluationPoint)
            .where(ForecastEvaluationPoint.ticker == ticker)
            .order_by(ForecastEvaluationPoint.origin)
        ):
            origins_by_model.setdefault(p.model, []).append(p.origin)
            assert index[p.window_end] - index[p.origin] == 21
        assert set(origins_by_model) == {"ewma", "combination", "garch", "rv_c2c_20", "implied"}
        origins = origins_by_model["ewma"]
        assert all(v == origins for v in origins_by_model.values())
        assert len(origins) == 10
        covered: set[int] = set()
        for o in origins:
            window = set(range(index[o] + 1, index[o] + 22))
            assert not window & covered
            covered |= window
        assert max(covered) == len(days) - 1 == index[LAST]


def test_evaluations_and_minimum_samples(forecasted: Session) -> None:
    s = forecasted
    for ticker in TICKERS:
        ev = {
            e.model: e
            for e in s.scalars(select(ForecastEvaluation).where(ForecastEvaluation.ticker == ticker))
        }
        assert ev["ewma"].n_windows == 7 and ev["ewma"].status == "insufficient_data"
        assert ev["ewma"].rmse is None, "abaixo da amostra mínima não há número (RN-PRV-02)"
        assert ev["combination"].n_windows == 9 and ev["combination"].status == "ok"
        assert ev["rv_c2c_20"].n_windows == 9 and ev["rv_c2c_20"].status == "ok"
        assert ev["garch"].n_windows == 0 and ev["garch"].discarded == {
            "no_forecast": 10,
            "incomplete_realized": 0,
        }
        assert ev["implied"].n_windows == 0
        comb = ev["combination"]
        assert comb.rmse is not None and comb.rmse_ci_low is not None and comb.rmse_ci_high is not None
        assert comb.rmse_ci_low <= comb.rmse <= comb.rmse_ci_high
        assert comb.ratios["rv_c2c_20"]["status"] == "ok" and comb.ratios["rv_c2c_20"]["n"] == 9
        assert comb.ratios["implied"]["status"] == "insufficient_data"
        assert comb.engine_version and comb.config_version_id
        # RMSE confere com os pontos gravados.
        pts = s.execute(
            select(ForecastEvaluationPoint.forecast, ForecastEvaluationPoint.realized).where(
                ForecastEvaluationPoint.ticker == ticker,
                ForecastEvaluationPoint.model == "combination",
                ForecastEvaluationPoint.discard_reason.is_(None),
            )
        ).all()
        e = np.array([float(f or 0) - float(r or 0) for f, r in pts])
        assert comb.rmse == pytest.approx(float(np.sqrt(np.mean(e * e))), rel=1e-12)


def test_latest_forecasts(forecasted: Session) -> None:
    s = forecasted
    rows = {
        r.model: r
        for r in s.scalars(select(RvForecast).where(RvForecast.ticker == "PETR4", RvForecast.as_of == LAST))
    }
    assert set(rows) == {"ewma", "combination", "garch"}
    garch = rows["garch"]
    assert (
        garch.status == "insufficient_data" and garch.vol is None and "mínimo de 240" in (garch.reason or "")
    )
    ewma = rows["ewma"]
    assert ewma.status == "ok" and ewma.vol is not None
    # Sem avaliação suficiente → intervalo χ², rotulado aproximado (QA-07).
    assert ewma.ci_origin == "approximate" and "erro de amostragem" in (ewma.ci_reason or "")
    assert ewma.ci_low is not None and ewma.ci_high is not None and ewma.ci_low < ewma.vol < ewma.ci_high
    comb = rows["combination"]
    assert comb.ci_origin == "estimated"
    # Combinação = média das variâncias (janela 20) de close-to-close, Yang-Zhang e Rogers-Satchell
    # (intradiária: 11 pregões < 20, fica fora).
    parts = [
        s.get(RealizedVol, ("PETR4", LAST, est, 20))
        for est in ("close_to_close", "yang_zhang", "rogers_satchell")
    ]
    assert all(p is not None and p.variance_annual is not None for p in parts)
    expected = float(np.sqrt(np.mean([p.variance_annual for p in parts if p and p.variance_annual])))
    assert comb.vol == pytest.approx(expected, rel=1e-12)
    assert comb.state["components"] == ["close_to_close", "yang_zhang", "rogers_satchell"]


def test_forecast_job_is_idempotent(forecasted: Session) -> None:
    before = _state(forecasted)
    _forecast(forecasted)
    assert _state(forecasted) == before


# --- API ----------------------------------------------------------------------------------------


@pytest.fixture
def loaded(
    make_session: sessionmaker[Session], tmp_path: Path, fixture_settings: None, api_client: TestClient
) -> Iterator[TestClient]:
    with make_session() as s:
        _collect(s, tmp_path)
        _recompute(s)
        _forecast(s)
    yield api_client


def test_forecasts_endpoint(loaded: TestClient) -> None:
    c = loaded
    r = c.get("/forecasts", params={"underlying": "petr4"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["as_of"] == "2026-11-19" and body["horizon_bd"] == 21 and body["selected_model"] == "ewma"
    items = {i["model"]: i for i in body["items"]}
    assert list(items) == ["ewma", "combination", "garch", "rv_c2c_20", "implied"]
    assert items["ewma"]["selected"] and not items["ewma"]["eligible"]
    assert "7 de 8" in items["ewma"]["eligibility_reason"]
    assert items["ewma"]["forecast"]["origin"] == "approximate"
    assert items["combination"]["eligible"] and items["combination"]["forecast"]["origin"] == "estimated"
    assert items["garch"]["forecast"]["status"] == "insufficient_data"
    assert items["garch"]["forecast"]["value"] is None
    assert items["rv_c2c_20"]["kind"] == "baseline" and items["rv_c2c_20"]["forecast"]["status"] == "ok"
    assert items["ewma"]["state"]["ewma_lambda"] == 0.94

    # Horizonte fora da avaliação: calculado do estado; EWMA plana; intervalo aproximado.
    r42 = c.get("/forecasts", params={"underlying": "PETR4", "horizon_bd": 42}).json()
    i42 = {i["model"]: i for i in r42["items"]}
    assert i42["ewma"]["forecast"]["value"] == pytest.approx(items["ewma"]["forecast"]["value"])
    assert i42["combination"]["forecast"]["origin"] == "approximate"
    assert "21 pregões" in i42["combination"]["forecast"]["reason"]
    assert i42["implied"]["forecast"]["status"] == "unavailable"

    assert c.get("/forecasts", params={"underlying": "XXXX3"}).status_code == 404
    assert (
        c.get("/forecasts", params={"underlying": "PETR4", "model": "garch"}).json()["items"][0]["model"]
        == "garch"
    )


def test_models_evaluation_endpoints(loaded: TestClient) -> None:
    c = loaded
    body = c.get("/models/evaluation", params={"underlying": "PETR4"}).json()
    assert body["horizon_bd"] == 21 and body["min_windows"] == 8 and body["ci_level"] == 0.9
    rows = {r["model"]: r for r in body["rows"]}
    assert rows["ewma"]["rmse"]["status"] == "insufficient_data" and rows["ewma"]["rmse"]["value"] is None
    assert rows["ewma"]["bias"] is None
    comb = rows["combination"]
    assert (
        comb["rmse"]["status"] == "ok"
        and comb["rmse"]["ci_low"] <= comb["rmse"]["value"] <= comb["rmse"]["ci_high"]
    )
    ratios = {x["baseline"]: x for x in comb["ratios"]}
    assert (
        ratios["rv_c2c_20"]["ratio"]["status"] == "ok"
        and ratios["implied"]["ratio"]["status"] == "insufficient_data"
    )
    assert rows["rv_c2c_20"]["kind"] == "baseline"

    pts = c.get("/models/evaluation/points", params={"underlying": "PETR4"}).json()
    series = {x["model"]: x["points"] for x in pts["series"]}
    assert len(series["combination"]) == 10
    assert series["garch"][0]["discard_reason"] == "no_forecast"


def test_model_selection(loaded: TestClient) -> None:
    c = loaded
    r = c.put("/models/selection", json={"model": "garch"})
    assert r.status_code == 409, "GARCH sem avaliação não pode ser escolhido (RF-PRV-02)"
    r = c.put("/models/selection", json={"model": "combination"})
    assert r.status_code == 200 and r.json()["created"] is True
    again = c.put("/models/selection", json={"model": "combination"}).json()
    assert again["created"] is False and again["config_version_id"] == r.json()["config_version_id"]
    assert c.get("/forecasts", params={"underlying": "PETR4"}).json()["selected_model"] == "combination"
    assert c.put("/models/selection", json={"model": "outro"}).status_code == 422
    cross = c.put("/models/selection", json={"model": "ewma"}, headers={"Origin": "https://evil.example"})
    assert cross.status_code == 403


def test_realized_close_to_close_has_chi2_interval(loaded: TestClient) -> None:
    body = loaded.get("/underlyings/PETR4/vol/realized").json()
    for e in body["estimators"]:
        latest = e["latest"]
        if latest["status"] != "ok":
            continue
        if e["estimator"] in ("close_to_close", "close_to_close_demeaned"):
            assert latest["ci_low"] < latest["value"] < latest["ci_high"]
        else:
            assert latest["ci_low"] is None and "distribuição fechada" in latest["reason"]
