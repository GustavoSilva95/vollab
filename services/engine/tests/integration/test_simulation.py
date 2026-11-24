"""Simulador, dimensionamento e registro da entrada com as fixtures reais (PRD 1.9 §5.8, §7 e §10.2).

Nas fixtures só PETR4 tem IV (19/11/2026; vencimentos com IV de referência: 18/12 e 15/01). Com o
modelo padrão (EWMA, 7 de 8 janelas) o semáforo fica indisponível; com a combinação ele dá edge de
**compra** de vol (σ̂ inflado pelos gaps de 26/10 das fixtures).
"""

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.integration.test_forecast import forecasted  # noqa: F401
from vollab.db.models import ConfigVersion, ManualInput, Position, PositionEntry

pytestmark = pytest.mark.integration
NOW = "2026-11-19T17:30:00-03:00"


def _chain(api: TestClient) -> dict[str, Any]:
    r = api.get("/underlyings/PETR4/chain")
    assert r.status_code == 200
    return dict(r.json())


def _body(chain: dict[str, Any], structure: str, **extra: Any) -> dict[str, Any]:
    return {
        "ticker": "PETR4",
        "structure": structure,
        "legs": [{"series_id": i} for i in chain["suggestions"][structure]],
    } | extra


def _counts(s: Session) -> tuple[int, ...]:
    return tuple(
        s.scalar(select(func.count()).select_from(m)) or 0 for m in (Position, PositionEntry, ManualInput)
    )


def test_chain_defaults_to_first_expiry_with_iv(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    c = _chain(api_client)
    assert c["as_of"] == "2026-11-19" and c["spot_brl"] == "42.67"
    assert c["expiry"] == "2026-12-18" and c["days_to_expiry_bd"] == 20
    assert c["expiries_with_iv"][0] == "2026-12-18"
    assert set(c["suggestions"]) == {
        "short_straddle", "long_straddle", "short_strangle", "long_strangle", "covered_call",
    }  # fmt: skip
    by_id = {s["series_id"]: s for s in c["series"]}
    call, put = (by_id[i] for i in c["suggestions"]["long_straddle"])
    assert (call["option_type"], put["option_type"]) == ("call", "put")
    assert call["effective_strike"] == put["effective_strike"]
    assert all(by_id[i]["iv"] is not None for ids in c["suggestions"].values() for i in ids)
    other = api_client.get("/underlyings/PETR4/chain", params={"expiry": "2027-01-15"}).json()
    assert other["expiry"] == "2027-01-15"
    assert api_client.get("/underlyings/XXXX3/chain").status_code == 404


def test_simulation_unavailable_with_unevaluated_model(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    c = _chain(api_client)
    r = api_client.post("/simulations", json=_body(c, "long_straddle"))
    assert r.status_code == 200
    sim = r.json()
    assert sim["model"] == "ewma" and sim["state"] == "unavailable"
    assert "7 de 8 janelas" in sim["reason"]
    assert sim["distribution"]["status"] == "unavailable"
    # Payoff e Greeks não dependem da previsão (RF-SIM-02).
    assert [cv["label"] for cv in sim["payoff"]["curves"]] == ["hoje", "metade da vida", "vencimento"]
    assert sim["greeks_lot"]["vega_per_point_brl"] > 0


def test_long_straddle_edge_distribution_and_sizing(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    s = forecasted
    assert api_client.put("/models/selection", json={"model": "combination"}).status_code == 200
    c = _chain(api_client)
    before = _counts(s), s.scalar(select(func.count()).select_from(ConfigVersion))
    body = _body(c, "long_straddle", capital_brl="100000", lots=3)
    r = api_client.post("/sizing", json=body)
    assert r.status_code == 200, r.text
    after = _counts(s), s.scalar(select(func.count()).select_from(ConfigVersion))
    assert before == after, "endpoints de cálculo não gravam nada (PRD §7)"
    sim, sz = r.json()["simulation"], r.json()["sizing"]

    assert (sim["state"], sim["signal_direction"], sim["direction"]) == ("edge", "buy", "buy")
    assert sim["direction_match"] and sim["horizon_bd"] == 20 and sim["lot_size"] == 100
    assert [leg["quantity_per_lot"] for leg in sim["legs"]] == [100, 100]
    assert sim["iv"]["origin"] == "observed" and 0.3 < sim["iv"]["value"] < 0.35
    # Mesmas definições do ranking (PRD §5.6): p = IV − σ̂(1 + s).
    iv, f, ns = sim["iv"]["value"], sim["forecast"]["value"], sim["normal_spread"]["value"]
    assert sim["premium"]["value"] == pytest.approx(iv - f * (1 + ns))
    assert sim["premium"]["ci_high"] < -sim["required_buy"]
    costs = sim["costs"]
    assert costs["total_buy_vol_pts"] == pytest.approx(costs["options_vol_pts"] + costs["hedge_buy_vol_pts"])
    assert float(costs["band_hedge_cost_brl"]) > 0
    # Greeks da posição = lote × lotes.
    assert sim["greeks_position"]["vega_per_point_brl"] == pytest.approx(
        3 * sim["greeks_lot"]["vega_per_point_brl"]
    )

    d = sim["distribution"]
    assert d["status"] == "ok" and d["origin"] == "estimated"
    assert (d["paths"], d["sample_size"], d["delta_band"], d["delta_band_calibrated"]) == (
        10_000,
        220,
        0.1,
        False,
    )
    assert d["iv_constant"] and d["mean_rehedges"] > 0
    assert sum(d["hist_counts"]) == 10_000
    pct = {p["percentile"]: float(p["pnl_brl"]) for p in d["percentiles"]}
    assert pct[1] <= pct[50] <= pct[99]
    assert float(d["es_brl"]) >= -pct[1] - 0.01
    assert sim["expected_pnl_brl"] == d["mean_brl"]
    assert d["kamal_derman_std_brl"] is not None

    # Dimensionamento (RN-SIZ-02..04): μ no limite inferior do edge, σ² simulado, teto por ES/stress.
    assert sz["status"] == "ok"
    mu = float(sz["mu_brl"])
    vega_unit = abs(sim["greeks_lot"]["vega_per_point_brl"]) * 100 / 100
    assert mu == pytest.approx(
        vega_unit * 100 * (-sim["premium"]["ci_high"] - costs["total_buy_vol_pts"]), abs=0.005
    )
    assert float(sz["max_loss_brl"]) == pytest.approx(
        max(float(sz["es_brl"]), *(float(x["loss_brl"]) for x in sz["stress"])), abs=0.01
    )
    assert sz["n_kelly"] == int(0.25 * 100_000 * mu / sz["variance_brl2"])
    assert sz["n_cap"] == int(0.07 * 100_000 / float(sz["max_loss_brl"]))
    assert sz["n_final"] == min(sz["n_kelly"], sz["n_cap"]) > 0
    assert sz["rule"] == ("cap" if sz["n_cap"] < sz["n_kelly"] else "kelly")
    assert [x["name"] for x in sz["stress"]] == ["gap_down", "gap_up", "vol_up", "down_vol_up"]

    # Determinismo pela semente.
    again = api_client.post("/sizing", json=body).json()
    assert again["simulation"]["distribution"] == d
    assert again["sizing"] == sz


def test_opposite_direction_gives_zero_with_reason(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    api_client.put("/models/selection", json={"model": "combination"})
    c = _chain(api_client)
    for structure in ("short_straddle", "short_strangle", "covered_call"):
        r = api_client.post("/sizing", json=_body(c, structure, capital_brl="100000"))
        assert r.status_code == 200, r.text
        sim, sz = r.json()["simulation"], r.json()["sizing"]
        assert sim["direction"] == "sell" and sim["state"] == "edge" and not sim["direction_match"]
        assert (sz["n_final"], sz["rule"]) == (0, "zero")
        assert "oposta" in sz["reason"]
        assert sz["n_cap"] is not None  # o teto continua informado
    cc = api_client.post("/simulations", json=_body(c, "covered_call")).json()
    assert cc["stock"] == {"quantity_per_lot": 100, "price_brl": "42.67"}
    assert not cc["dynamic_hedge"] and cc["distribution"]["mean_rehedges"] == 0
    assert cc["greeks_lot"]["delta_shares"] > 0  # ação comprada + call vendida


def test_sizing_without_capital_is_unavailable(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    api_client.put("/models/selection", json={"model": "combination"})
    sz = api_client.post("/sizing", json=_body(_chain(api_client), "long_straddle")).json()["sizing"]
    assert sz["status"] == "unavailable" and sz["n_final"] == 0 and "capital" in sz["reason"]


def test_manual_prices_recompute_iv_and_are_labeled(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    api_client.put("/models/selection", json={"model": "combination"})
    c = _chain(api_client)
    call_id, put_id = c["suggestions"]["long_straddle"]
    body = {
        "ticker": "PETR4",
        "structure": "long_straddle",
        "legs": [
            {"series_id": call_id, "manual_price_brl": "1.80", "manual_price_at": NOW},
            {"series_id": put_id},
        ],
        "manual_spot_brl": "42.50",
        "manual_spot_at": NOW,
    }
    sim = api_client.post("/simulations", json=body).json()
    call, put = sim["legs"]
    assert (call["price_brl"], call["price_origin"], call["iv"]["origin"]) == ("1.80", "manual", "manual")
    assert put["price_origin"] == "estimated" and put["iv"]["origin"] == "observed"
    assert sim["spot_origin"] == "manual" and sim["spot_brl"] == "42.50"
    assert sim["iv"]["origin"] == "manual" and sim["premium"]["origin"] == "manual"
    # Ida e volta: a IV recalculada reprecifica o preço manual.
    from vollab.quant.pricing import bs_price

    t = sim["horizon_bd"] / 252
    from math import log1p

    price = float(bs_price(42.5, call["effective_strike"], t, log1p(sim["rate"]), call["iv"]["value"], True))
    assert price == pytest.approx(1.80, abs=1e-8)

    # Erros de entrada: sem hora, preço impossível, pernas incoerentes.
    no_time = body | {"manual_spot_at": None}
    assert api_client.post("/simulations", json=no_time).status_code == 422
    absurd = body | {"legs": [{"series_id": call_id, "manual_price_brl": "60", "manual_price_at": NOW},
                              {"series_id": put_id}]}  # fmt: skip
    r = api_client.post("/simulations", json=absurd)
    assert r.status_code == 422 and "sem IV" in r.json()["detail"]
    wrong = _body(c, "long_straddle") | {"structure": "long_strangle"}
    r = api_client.post("/simulations", json=wrong)
    assert r.status_code == 422 and "strike" in r.json()["detail"]


def _entry(sim: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "ticker": "PETR4",
        "structure": sim["structure"],
        "legs": [{"series_id": leg["series_id"]} for leg in sim["legs"]],
        "capital_brl": "100000",
        "base_config_version_id": sim["config_version_id"],
        "executed_legs": [
            {"series_id": leg["series_id"], "price_brl": leg["price_brl"], "fees_brl": "0.20"}
            for leg in sim["legs"]
        ],
        "executed_at": NOW,
        "lots": 2,
    } | extra


def test_register_entry_records_immutable_snapshot(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
    owner_session: Session,
) -> None:
    s = forecasted
    api_client.put("/models/selection", json={"model": "combination"})
    c = _chain(api_client)
    sim = api_client.post("/simulations", json=_body(c, "long_straddle")).json()

    stale = api_client.post("/positions", json=_entry(sim, base_config_version_id=1))
    assert stale.status_code == 409

    r = api_client.post(
        "/positions",
        json=_entry(
            sim, margin_per_lot_brl="250", margin_at=NOW, manual_spot_brl="42.67", manual_spot_at=NOW
        ),
    )
    assert r.status_code == 201, r.text
    pos = r.json()
    assert (pos["edge_state"], pos["direction"], pos["lots"], pos["overridden"]) == ("edge", "buy", 2, False)
    assert pos["model"] == "combination" and pos["config_version_id"] == sim["config_version_id"]
    snap = pos["decision_snapshot"]
    # PRD §5.4: semáforo, edge com intervalo, spread normal, IV, σ̂, modelo, custos, simulação resumida,
    # Kelly × teto, sugerido × executado, configuração, versão do engine e entradas manuais.
    assert snap["simulation"]["state"] == "edge"
    assert snap["simulation"]["premium"]["ci_low"] is not None
    assert snap["simulation"]["normal_spread"]["calibrated"] is False
    assert snap["simulation"]["config_version_id"] == sim["config_version_id"]
    assert snap["simulation"]["engine_version"]
    assert snap["sizing"]["rule"] in {"kelly", "cap", "tie"}
    assert snap["executed"]["lots"] == 2 and snap["executed"]["suggested_lots"] == snap["sizing"]["n_final"]
    assert "payoff" not in snap["simulation"] and "hist_counts" not in snap["simulation"]["distribution"]
    assert snap["simulation"]["distribution"]["es_brl"] is not None
    assert [(e["kind"], e["quantity"]) for e in pos["entries"]] == [("entry", 200), ("entry", 200)]
    assert {m["kind"] for m in pos["manual_inputs"]} == {"spot", "margin"}

    listed = api_client.get("/positions").json()
    assert [p["id"] for p in listed] == [pos["id"]]
    assert api_client.get(f"/positions/{pos['id']}").json()["decision_snapshot"] == snap
    assert api_client.get("/positions/999999").status_code == 404

    # Imutável: o papel da aplicação não tem UPDATE/DELETE, e o trigger barra até o dono.
    with pytest.raises(DBAPIError, match=r"permission denied|permissão negada"):
        s.execute(text("UPDATE positions SET lots = 3"))
    s.rollback()
    with pytest.raises(DBAPIError, match="imutável"):
        owner_session.execute(text("UPDATE positions SET lots = 3"))
    owner_session.rollback()
    with pytest.raises(DBAPIError, match="imutável"):
        owner_session.execute(text("DELETE FROM position_entries"))
    owner_session.rollback()
    assert _counts(s) == (1, 2, 2)


def test_register_requires_semaphore_and_override(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
) -> None:
    s = forecasted
    c = _chain(api_client)
    # EWMA (padrão) sem avaliação: semáforo indisponível → nunca entra (CS-01).
    sim = api_client.post("/simulations", json=_body(c, "long_straddle")).json()
    r = api_client.post("/positions", json=_entry(sim, override_reason="quero entrar mesmo assim"))
    assert r.status_code == 422 and "indisponível" in r.json()["detail"]

    api_client.put("/models/selection", json={"model": "combination"})
    short = api_client.post("/simulations", json=_body(c, "short_straddle")).json()
    r = api_client.post("/positions", json=_entry(short))
    assert r.status_code == 422 and "override_reason" in r.json()["detail"]
    r = api_client.post("/positions", json=_entry(short, override_reason="teste de entrada contra o sinal"))
    assert r.status_code == 201
    pos = r.json()
    assert pos["overridden"] and pos["direction"] == "sell" and pos["edge_state"] == "edge"
    assert pos["decision_snapshot"]["override"]["reasons"] == ["direção da estrutura oposta à do sinal",
                                                              "2 lote(s) acima do sugerido (0)"]  # fmt: skip
    assert [e["quantity"] for e in pos["entries"]] == [-200, -200]

    long = api_client.post("/simulations", json=_body(c, "long_straddle")).json()
    too_many = api_client.post("/positions", json=_entry(long, lots=10_000))
    assert too_many.status_code == 422 and "acima do sugerido" in too_many.json()["detail"]

    # Venda coberta exige a ação; pernas executadas devem bater.
    cc = api_client.post("/simulations", json=_body(c, "covered_call")).json()
    r = api_client.post("/positions", json=_entry(cc, override_reason="teste de venda coberta"))
    assert r.status_code == 422 and "200 ações" in r.json()["detail"]
    ok = _entry(cc, override_reason="teste de venda coberta", stock={"quantity": 200, "price_brl": "42.67"})
    r = api_client.post("/positions", json=ok)
    assert r.status_code == 201
    assert [(e["instrument"], e["quantity"]) for e in r.json()["entries"]][-1] == ("PETR4", 200)
    bad = _entry(long) | {"executed_legs": [{"series_id": 1, "price_brl": "1"}]}
    assert api_client.post("/positions", json=bad).status_code == 422
    assert _counts(s)[0] == 2
    assert s.scalar(select(Position.as_of).limit(1)) == date(2026, 11, 19)
