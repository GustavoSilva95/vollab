"""Custos, edge e ranking com as fixtures reais (PRD 1.8 §5.6.1, §7; RF-RNK-01/02, RN-CST-03).

Nas fixtures só PETR4 tem IV (19/11/2026, um vencimento com ATM → fallback com prazo efetivo de
20 du, tudo `approximate`); BBAS3 e BOVA11 ficam indisponíveis. Nenhuma origem da avaliação tem IV
de prazo constante → spread normal não calibrado (15%). EWMA tem 7 janelas (< 8): com o padrão, o
edge fica indisponível; a combinação tem 9 e alimenta o edge.
"""

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.integration.test_forecast import forecasted  # noqa: F401
from tests.integration.test_vol_recompute import _recompute
from vollab.db.models import ConfigVersion, OptionSpreadEstimate

pytestmark = pytest.mark.integration


def _spreads(session: Session) -> list[tuple[Any, ...]]:
    return [
        tuple(r)
        for r in session.execute(
            text(
                "SELECT ticker, trade_date, band, n_series, n_trades, rel_median, rel_p75, quoted_rel_median "
                "FROM option_spread_estimates ORDER BY 1, 2, 3"
            )
        )
    ]


def test_spread_estimates_written_per_band_and_idempotent(forecasted: Session) -> None:  # noqa: F811
    s = forecasted
    rows = _spreads(s)
    assert rows, "o vol_recompute deve gravar o spread"
    by_day: dict[tuple[object, object], set[object]] = {}
    for r in rows:
        by_day.setdefault((r[0], r[1]), set()).add(r[2])
    assert all(bands == {"low", "atm", "high", "underlying"} for bands in by_day.values())
    petr = {r[2]: r for r in rows if r[0] == "PETR4" and r[1] == date(2026, 11, 19)}
    atm, und = petr["atm"], petr["underlying"]
    assert isinstance(atm[3], int) and atm[3] > 0
    assert 0 < float(atm[5]) <= float(atm[6]) < 0.1  # relativo em decimal, p75 ≥ mediana
    assert 0 < float(und[5]) < 0.01  # ativo-objeto: ~1 tick sobre ~R$ 40
    _recompute(s)
    assert _spreads(s) == rows


def test_ranking_unavailable_without_evaluated_model(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    body = api_client.get("/ranking").json()
    assert body["selected_model"] == "ewma"
    rows = {r["ticker"]: r for r in body["rows"]}
    petr = rows["PETR4"]
    assert petr["state"] == "unavailable"
    assert "7 de 8 janelas" in petr["reason"]
    assert petr["iv"]["status"] == "ok" and petr["iv"]["origin"] == "approximate"
    assert petr["premium"]["value"] is None
    for t in ("BBAS3", "BOVA11"):
        assert rows[t]["state"] == "unavailable"
        assert "sem IV de prazo constante" in rows[t]["reason"]


def test_ranking_with_combination(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    s = forecasted
    assert api_client.put("/models/selection", json={"model": "combination"}).status_code == 200
    before = {
        "versions": s.scalar(select(func.count()).select_from(ConfigVersion)),
        "spreads": s.scalar(select(func.count()).select_from(OptionSpreadEstimate)),
    }
    body = api_client.get("/ranking").json()
    after = {
        "versions": s.scalar(select(func.count()).select_from(ConfigVersion)),
        "spreads": s.scalar(select(func.count()).select_from(OptionSpreadEstimate)),
    }
    assert before == after, "o ranking é cálculo de leitura: não grava nada"
    assert [r["position"] for r in body["rows"]] == [1, 2, 3]
    petr = body["rows"][0]
    assert petr["ticker"] == "PETR4"
    assert petr["state"] in {"edge", "inconclusive", "no_edge"}
    assert petr["approximate"] and petr["horizon_bd"] == 20
    assert "sem prazo constante" in petr["reason"]
    # Spread normal e limiar não calibrados (RN-EDG-05/07), nunca zero implícito.
    ns = petr["normal_spread"]
    assert (ns["value"], ns["calibrated"], ns["origin"]) == (0.15, False, "manual")
    assert "não calibrado" in ns["reason"]
    thr = petr["threshold"]
    assert (thr["value"], thr["calibrated"], thr["origin"]) == (0.01, False, "manual")
    # Definições (PRD §5.6): p = IV − σ̂(1 + s); edge relativo = p/σ̂.
    iv, f = petr["iv"]["value"], petr["forecast"]["value"]
    assert petr["premium"]["value"] == pytest.approx(iv - f * 1.15)
    assert petr["relative_edge"]["value"] == pytest.approx(petr["premium"]["value"] / f)
    assert petr["premium"]["origin"] == "approximate"
    c = petr["costs"]
    assert c["option_spread_conservative"] >= c["option_spread_central"] > 0
    assert c["total_sell_vol_pts"] == pytest.approx(c["options_vol_pts"] + c["hedge_sell_vol_pts"])
    assert c["options_vol_pts"] < 0.02  # PRD 1.8.1: o spread de fechamento fica fora do custo
    assert petr["required_sell"] == pytest.approx(c["total_sell_vol_pts"] + 0.01)
    # Consistência do estado com o intervalo do prêmio.
    lo, hi = petr["premium"]["ci_low"], petr["premium"]["ci_high"]
    if petr["state"] == "edge":
        assert lo > petr["required_sell"] or hi < -petr["required_buy"]
    assert petr["liquidity"]["liquid_series"] > 0
    assert body["config_version_id"] > 0 and body["engine_version"]

    one = api_client.get("/ranking", params={"underlying": "petr4"}).json()
    assert [r["ticker"] for r in one["rows"]] == ["PETR4"]


def test_config_versioning_changes_the_ranking(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    api_client.put("/models/selection", json={"model": "combination"})
    current = api_client.get("/config").json()
    assert current["params"]["edge"]["threshold_vol_pts"] == 0.01
    assert current["params"]["costs"]["brokerage_per_order_brl"] == 0.0
    # Mesmos parâmetros: nada gravado.
    same = api_client.post("/config", json={"params": current["params"], "note": "sem mudança"})
    assert same.status_code == 201 and same.json() == {"id": current["id"], "created": False}
    # Limiar enorme: nenhuma direção pode dar edge líquido.
    params = current["params"]
    params["edge"]["threshold_vol_pts"] = 0.2
    created = api_client.post("/config", json={"params": params, "note": "limiar de teste"})
    assert created.status_code == 201 and created.json()["created"] is True
    new_id = created.json()["id"]
    petr = next(r for r in api_client.get("/ranking").json()["rows"] if r["ticker"] == "PETR4")
    assert petr["state"] in {"inconclusive", "no_edge"}
    assert petr["threshold"]["value"] == 0.2
    versions = api_client.get("/config/versions").json()
    assert versions[0]["id"] == new_id and versions[0]["current"] and versions[0]["note"] == "limiar de teste"
    assert (
        api_client.get(f"/config/versions/{current['id']}").json()["params"]["edge"]["threshold_vol_pts"]
        == 0.01
    )
    assert api_client.get("/config/versions/999999").status_code == 404
    # O Pydantic valida o snapshot inteiro (422 com o campo).
    params["edge"]["threshold_vol_pts"] = -1
    bad = api_client.post("/config", json={"params": params, "note": "inválido"})
    assert bad.status_code == 422
    params["edge"]["threshold_vol_pts"] = 0.01
    params["costs"]["moneyness_bands"] = [1.05, 0.95]
    assert api_client.post("/config", json={"params": params, "note": "inválido"}).status_code == 422
    params["costs"]["moneyness_bands"] = [0.95, 1.05]
    params["costs"]["unknown"] = 1
    assert api_client.post("/config", json={"params": params, "note": "inválido"}).status_code == 422


def test_spreads_endpoint(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    body = api_client.get("/underlyings/PETR4/spreads", params={"days": 2}).json()
    assert body["moneyness_bands"] == [0.95, 1.05]
    assert len({d["trade_date"] for d in body["days"]}) == 2
    assert len(body["days"]) == 8
    assert api_client.get("/underlyings/XXXX3/spreads").status_code == 404
