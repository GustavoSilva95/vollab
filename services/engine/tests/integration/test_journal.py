"""Diário, marcação D-1, atribuição, carteira, stress, limites e crise com as fixtures reais (PRD 1.10
§5.9 e §10.2; BRD 1.7 RF-DIA-02..04, RF-RSK-01..04, RS-06, CS-04, QA-12).

PETR4 nas fixtures: straddle vendido de dez/26 (PETRL44 call e PETRX44 put, europeias, IV de
referência em 17, 18 e 19/11/2026). A operação é gravada direto no banco com entrada em 17/11 (o
registro pelo simulador só aceita o último pregão), para haver três pregões de marcação.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.conftest import FIXTURES
from tests.integration.test_forecast import forecasted  # noqa: F401
from tests.integration.test_simulation import _body, _chain, _entry
from tests.integration.test_vol_recompute import recomputed  # noqa: F401
from vollab.analytics.crisis import CrisisMeasurer
from vollab.analytics.journal import JOB_KIND, MarksComputer, run_marks_job
from vollab.collection.params import ensure_config_version
from vollab.data.raw_cache import RawCache
from vollab.data.sources import FixtureSources
from vollab.db.models import (
    FIXED_USER_ID,
    CrisisMeasurement,
    DailyMark,
    Job,
    JobStatus,
    OptionSeries,
    PnlAttribution,
    Position,
    PositionEntry,
)

pytestmark = pytest.mark.integration
ENTRY_AT = datetime(2026, 11, 17, 18, 0, tzinfo=UTC)  # 15:00 em Brasília


def _series(s: Session, code: str) -> OptionSeries:
    row = s.scalar(
        select(OptionSeries).where(OptionSeries.code == code, OptionSeries.expiry == date(2026, 12, 18))
    )
    assert row is not None
    return row


def _short_straddle(s: Session) -> Position:
    version = ensure_config_version(s, user_id=FIXED_USER_ID)
    call, put = _series(s, "PETRL44"), _series(s, "PETRX44")
    p = Position(
        user_id=FIXED_USER_ID,
        ticker="PETR4",
        structure="short_straddle",
        direction="sell",
        expiry=date(2026, 12, 18),
        as_of=date(2026, 11, 17),
        lots=1,
        edge_state="edge",
        model="combination",
        config_version_id=version.id,
        engine_version="test",
        decision_snapshot={"simulation": {"legs": [{"series_id": call.id}, {"series_id": put.id}]}},
    )
    s.add(p)
    s.flush()
    for leg, price in ((call, "2.40"), (put, "1.05")):
        s.add(
            PositionEntry(
                position_id=p.id,
                user_id=FIXED_USER_ID,
                kind="entry",
                instrument=leg.code,
                series_id=leg.id,
                quantity=-100,
                price=Decimal(price),
                fees_brl=Decimal("0.30"),
                brokerage_brl=Decimal(0),
                executed_at=ENTRY_AT,
            )
        )
    s.commit()
    return p


def _run_marks(s: Session) -> None:
    for job in s.scalars(select(Job).where(Job.kind == JOB_KIND, Job.status == JobStatus.QUEUED)).all():
        run_marks_job(s, dict(job.payload))
        job.status = JobStatus.SUCCEEDED
    s.commit()


MARKS_SQL = (
    "SELECT trade_date, spot, stock_qty, options_value, delta_shares, legs::text FROM daily_marks "
    "WHERE position_id = :p ORDER BY 1"
)
ATTR_SQL = (
    "SELECT trade_date, delta_brl, gamma_brl, theta_brl, vega_brl, market_brl, residual_brl, execution_brl, "
    "error_flag FROM pnl_attribution WHERE position_id = :p ORDER BY 1"
)


def _state(s: Session, pid: int) -> list[Any]:
    return [*s.execute(text(MARKS_SQL), {"p": pid}).all(), *s.execute(text(ATTR_SQL), {"p": pid}).all()]


def test_marks_and_attribution_on_real_data(recomputed: Session, fixture_settings: None) -> None:  # noqa: F811
    s = recomputed
    p = _short_straddle(s)
    MarksComputer(s, user_id=FIXED_USER_ID).run([p.id])
    s.commit()
    marks = s.scalars(
        select(DailyMark).where(DailyMark.position_id == p.id).order_by(DailyMark.trade_date)
    ).all()
    assert [m.trade_date for m in marks] == [date(2026, 11, 17), date(2026, 11, 18), date(2026, 11, 19)]
    assert [m.spot for m in marks] == [Decimal("43.98"), Decimal("43.17"), Decimal("42.67")]
    for m in marks:
        assert {leg["origin"] for leg in m.legs} == {"observed"}  # IV de referência nos três pregões
        assert all(
            {"is_call", "strike_eff", "days_to_expiry_bd", "rate_c", "pv_div"} <= leg.keys() for leg in m.legs
        )
        assert m.vega_per_point_brl < 0 and m.theta_per_bd_brl > 0 and not m.stale
    attrs = s.scalars(
        select(PnlAttribution).where(PnlAttribution.position_id == p.id).order_by(PnlAttribution.trade_date)
    ).all()
    assert len(attrs) == 3
    first = attrs[0]
    # Dia da entrada: só execução e custos (marcação − preço pago, menos taxas).
    assert (first.market_brl, first.delta_brl, first.residual_brl) == (Decimal(0),) * 3
    opening = sum(
        Decimal(leg["quantity"])
        * (Decimal(leg["price_brl"]) - {"PETRL44": Decimal("2.40")}.get(leg["code"], Decimal("1.05")))
        for leg in marks[0].legs
    ) - Decimal("0.60")
    assert first.execution_brl == opening
    for prev, cur, a in zip(marks, marks[1:], attrs[1:], strict=False):
        market = sum(
            Decimal(lc["quantity"]) * (Decimal(lc["price_brl"]) - Decimal(lp["price_brl"]))
            for lp, lc in zip(prev.legs, cur.legs, strict=True)
        )
        assert a.market_brl == market
        assert a.residual_brl == a.market_brl - (a.delta_brl + a.gamma_brl + a.theta_brl + a.vega_brl)
        assert a.execution_brl == 0
    # Fluxos de caixa: prêmios recebidos − taxas + valor das opções na última marcação.
    total = sum((a.market_brl + a.execution_brl for a in attrs), Decimal(0))
    cash = Decimal(100) * (Decimal("2.40") + Decimal("1.05")) - Decimal("0.60") + marks[-1].options_value
    assert total == cash
    # Idempotente: refazer dá o mesmo estado.
    before = _state(s, p.id)
    MarksComputer(s, user_id=FIXED_USER_ID).run([p.id])
    s.commit()
    assert _state(s, p.id) == before


def test_entries_void_status_and_journal_api(
    recomputed: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
    owner_session: Session,
) -> None:
    s = recomputed
    p = _short_straddle(s)
    url = f"/positions/{p.id}/entries"
    hedge = {"kind": "hedge", "instrument": "PETR4", "quantity": 30, "price_brl": "43.50",
             "fees_brl": "0.39", "executed_at": "2026-11-18T14:00:00-03:00"}  # fmt: skip
    r = api_client.post(url, json=hedge)
    assert r.status_code == 201, r.text
    pos = r.json()
    assert {h["instrument"]: h["quantity"] for h in pos["holdings"]} == {
        "PETR4": 30,
        "PETRL44": -100,
        "PETRX44": -100,
    }
    assert s.scalar(select(func.count()).select_from(Job).where(Job.kind == JOB_KIND)) == 1
    hedge_id = pos["entries"][-1]["id"]

    # RS-06: cada inconsistência volta 422 com o motivo.
    bad = [
        ({"kind": "exit", "instrument": "PETRX44", "quantity": 101, "price_brl": "1"}, "direção a zero"),
        ({"kind": "exercise", "instrument": "PETRL44", "quantity": 100, "price_brl": "44"}, "perna comprada"),
        ({"kind": "hedge", "instrument": "VALE3", "quantity": 10, "price_brl": "60"}, "não pertence"),
        ({"kind": "hedge", "instrument": "PETR4", "quantity": 10, "price_brl": "43",
          "executed_at": "2026-11-16T12:00:00-03:00"}, "anterior à entrada"),
        ({"kind": "void", "linked_entry_id": pos["entries"][0]["id"], "void_reason": "erro de digitação"},
         "entrada não se estorna"),
    ]  # fmt: skip
    for body, msg in bad:
        body.setdefault("executed_at", "2026-11-19T12:00:00-03:00")
        r = api_client.post(url, json=body)
        assert r.status_code == 422 and msg in r.json()["detail"], (body, r.text)
    assert (
        api_client.post(url, json={"kind": "void", "executed_at": "2026-11-19T12:00:00-03:00"}).status_code
        == 422
    )

    _run_marks(s)
    detail = api_client.get(f"/positions/{p.id}").json()
    assert [m["stock_qty"] for m in detail["marks"]] == [0, 30, 30]
    a18 = detail["attribution"][1]
    # Hedge executado em 18/11 a 43,50 e marcado no fechamento de 43,17: 30 × (43,17 − 43,50) − 0,39.
    assert Decimal(a18["execution_brl"]) == Decimal("-10.29")
    assert detail["cs04"]["ratio"] is not None and detail["cs04"]["target"] == 0.15
    assert detail["delta_band"]["state"] in {"inside", "outside"}
    assert detail["delta_band"]["half_width_shares"] == pytest.approx(10.0)  # 0,10 × 100 × 1 lote
    assert detail["totals"]["residual_brl"] is not None

    # Estorno do hedge: anulado, com o motivo; as quantidades voltam.
    void = {"kind": "void", "linked_entry_id": hedge_id, "executed_at": "2026-11-19T12:00:00-03:00"}
    r = api_client.post(url, json=void | {"void_reason": "hedge lançado em dobro"})
    assert r.status_code == 201, r.text
    pos = r.json()
    assert "PETR4" not in {h["instrument"] for h in pos["holdings"] if h["quantity"]}
    assert next(e for e in pos["entries"] if e["id"] == hedge_id)["voided_by"] == pos["entries"][-1]["id"]
    r = api_client.post(url, json=void | {"void_reason": "de novo, por engano"})
    assert r.status_code == 422 and "já foi estornado" in r.json()["detail"]

    # Encerramento: saídas das duas pernas → status derivado "closed"; só aceita estorno.
    for code in ("PETRL44", "PETRX44"):
        exit_ = {"kind": "exit", "instrument": code, "quantity": 100, "price_brl": "1.50"}
        r = api_client.post(url, json=exit_ | {"executed_at": "2026-11-19T16:00:00-03:00"})
        assert r.status_code == 201, r.text
    assert r.json()["status"] == "closed"
    assert api_client.get("/positions", params={"status": "closed"}).json()[0]["id"] == p.id
    assert api_client.get("/positions", params={"status": "open"}).json() == []
    r = api_client.post(url, json=hedge | {"executed_at": "2026-11-19T17:00:00-03:00"})
    assert r.status_code == 422 and "encerrada" in r.json()["detail"]
    _run_marks(s)
    listed = api_client.get("/positions").json()[0]
    assert listed["last_mark_date"] == "2026-11-19" and listed["pnl_total_brl"] is not None

    # Lançamentos imutáveis também para o estorno (o papel da aplicação não altera; o trigger barra o dono).
    with pytest.raises(DBAPIError, match=r"permission denied|permissão negada"):
        s.execute(text("DELETE FROM position_entries WHERE kind = 'void'"))
    s.rollback()
    with pytest.raises(DBAPIError, match="imutável"):
        owner_session.execute(text("UPDATE position_entries SET void_reason = 'x' WHERE kind = 'void'"))
    owner_session.rollback()


def test_portfolio_limits_and_crisis(
    recomputed: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
    tmp_path: Path,
) -> None:
    s = recomputed
    p = _short_straddle(s)
    MarksComputer(s, user_id=FIXED_USER_ID).run([p.id])
    s.commit()

    port = api_client.get("/portfolio").json()
    assert port["positions_open"] == 1 and port["mark_dates"] == {"PETR4": "2026-11-19"}
    assert port["total"]["vega_per_point_brl"] < 0 and port["total"]["gamma"] < 0
    assert [(e["ticker"], e["expiry"]) for e in port["by_expiry"]] == [("PETR4", "2026-12-18")]

    lim = api_client.get("/portfolio/limits").json()
    assert lim["capital_brl"] is None and {x["state"] for x in lim["limits"]} == {"unavailable"}
    names = [sc["name"] for sc in lim["scenarios"]]
    assert names[:4] == ["gap_up", "gap_down", "vol_up", "down_vol_up"]
    assert any("crise indisponível" in w.lower() or "crise" in w for w in lim["warnings"])
    vol_up = next(sc for sc in lim["scenarios"] if sc["name"] == "vol_up")
    assert Decimal(vol_up["loss_brl"]) > 0  # vendido em vol perde com alta de vol
    custom = api_client.post("/portfolio/stress", json={"spot_shock": -0.1, "vol_shock": 0.1}).json()
    assert (
        custom["loss_brl"] == next(sc for sc in lim["scenarios"] if sc["name"] == "down_vol_up")["loss_brl"]
    )

    # QA-12: medição com os recortes reais dos COTAHIST de 2017 e 2020.
    assert api_client.post("/risk/crisis/measure").status_code == 202
    CrisisMeasurer(
        s, user_id=FIXED_USER_ID, sources=FixtureSources(FIXTURES), cache=RawCache(tmp_path / "raw")
    ).run(None)
    s.commit()
    rows = {(m.ticker, m.episode): m for m in s.scalars(select(CrisisMeasurement))}
    petr = rows[("PETR4", "mar2020")]
    assert (petr.status, petr.vol_method, petr.window_start, petr.window_end) == (
        "ok",
        "atm_iv",
        date(2020, 3, 6),
        date(2020, 3, 12),
    )
    assert petr.price_shock == pytest.approx(-0.5018, abs=1e-4) and petr.vol_shock == pytest.approx(
        1.159, abs=1e-3
    )
    assert rows[("BOVA11", "mai2017")].vol_method == "rv20"  # opções de BOVA11 sem liquidez em 2017
    assert rows[("PETR4", "mai2017")].worst_day == date(2017, 5, 18)
    crisis = api_client.get("/risk/crisis").json()
    assert {v["origin"] for v in crisis["values"] if v["status"] == "ok"} == {"approximate"}

    # Capital informado → limites avaliados; a crise entra nos cenários.
    cfg = api_client.get("/config").json()
    params = cfg["params"]
    params["sizing"]["capital_brl"] = 100000
    params["risk"]["crisis_overrides"] = {"PETR4": {"mai2017": {"price_shock": -0.2, "vol_shock": 0.3}}}
    r = api_client.post(
        "/config", json={"params": params, "note": "capital e choque manual", "base_version_id": cfg["id"]}
    )
    assert r.status_code == 201, r.text
    lim = api_client.get("/portfolio/limits").json()
    crisis_names = {sc["name"]: sc for sc in lim["scenarios"] if sc["kind"] == "crisis"}
    assert set(crisis_names) == {"crisis_mai2017", "crisis_mar2020"}
    assert crisis_names["crisis_mai2017"]["origin"] == "manual"
    assert crisis_names["crisis_mar2020"]["origin"] == "approximate"
    stress = next(x for x in lim["limits"] if x["name"] == "stress_loss")
    worst = max(Decimal(sc["loss_brl"]) for sc in lim["scenarios"])
    assert stress["value"] == pytest.approx(float(worst) / 100000, rel=1e-6)
    assert (
        stress["state"] == ("breached" if stress["value"] > 0.20 else "ok") and stress["calibrated"] is False
    )


def test_sizing_crisis_cap_proforma_and_roll(
    forecasted: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
    tmp_path: Path,
) -> None:
    s = forecasted
    CrisisMeasurer(
        s, user_id=FIXED_USER_ID, sources=FixtureSources(FIXTURES), cache=RawCache(tmp_path / "raw")
    ).run(None)
    s.commit()
    api_client.put("/models/selection", json={"model": "combination"})
    # Os limites usam o capital da configuração, nunca o do pedido (revisão de segurança, M-1).
    cfg = api_client.get("/config").json()
    params = cfg["params"]
    params["sizing"]["capital_brl"] = 100000
    r = api_client.post("/config", json={"params": params, "note": "capital", "base_version_id": cfg["id"]})
    assert r.status_code == 201, r.text
    c = _chain(api_client)
    r = api_client.post("/sizing", json=_body(c, "long_straddle", capital_brl="999999999", lots=2))
    assert r.status_code == 200, r.text
    body = r.json()
    stress = {x["name"]: x for x in body["sizing"]["stress"]}
    assert {"crisis_mai2017", "crisis_mar2020"} <= set(stress)
    assert stress["crisis_mar2020"]["spot_shock"] == pytest.approx(-0.5018, abs=1e-4)
    assert float(body["sizing"]["max_loss_brl"]) == pytest.approx(
        max(float(body["sizing"]["es_brl"]), *(float(x["loss_brl"]) for x in stress.values())), abs=0.01
    )
    assert body["limits"] is not None and body["limits"]["capital_brl"] == "100000.00"
    assert {x["name"] for x in body["limits"]["limits"]} >= {"stress_loss", "vega_total"}

    # Registro → depois rolagem: a origem recebe os `roll`, a nova posição aponta para ela.
    sim = body["simulation"]
    first = api_client.post("/positions", json=_entry(sim))
    assert first.status_code == 201, first.text
    origin = first.json()
    assert "limits" in origin["decision_snapshot"]
    roll = {"position_id": origin["id"], "legs": [
        {"instrument": e["instrument"], "quantity": -e["quantity"], "price_brl": "1.00", "fees_brl": "0.10"}
        for e in origin["entries"]
    ]}  # fmt: skip
    bad = api_client.post("/positions", json=_entry(sim, roll_from=roll | {"legs": roll["legs"][:1] * 2}))
    assert bad.status_code == 422 and "Rolagem" in bad.json()["detail"]
    r = api_client.post("/positions", json=_entry(sim, roll_from=roll))
    assert r.status_code == 201, r.text
    new = r.json()
    assert new["rolled_from_position_id"] == origin["id"]
    after = api_client.get(f"/positions/{origin['id']}").json()
    assert after["status"] == "closed"
    assert [e["kind"] for e in after["entries"]] == ["entry", "entry", "roll", "roll"]
    r = api_client.post("/positions", json=_entry(sim, roll_from=roll))
    assert r.status_code == 422 and "encerrada" in r.json()["detail"]


def test_concurrent_exits_are_serialized_and_bad_ledger_does_not_break_reads(
    recomputed: Session,  # noqa: F811
    api_client: TestClient,
    fixture_settings: None,
    make_session: Any,
) -> None:
    """Revisão de segurança, B-1: duas saídas da mesma perna ao mesmo tempo. A trava da operação faz a
    segunda esperar e ser validada contra o estado com a primeira (422)."""
    s = recomputed
    p = _short_straddle(s)
    from vollab.analytics.journal import add_entry
    from vollab.api.schemas.journal import EntryCreate
    from vollab.quant.journal import LedgerError

    body = EntryCreate(
        kind="exit", instrument="PETRX44", quantity=100, price_brl=Decimal("1.5"),
        executed_at=datetime(2026, 11, 19, 19, 0, tzinfo=UTC),
    )  # fmt: skip
    version = ensure_config_version(s, user_id=FIXED_USER_ID).id
    s.commit()
    first, second = make_session(), make_session()
    try:
        p1 = first.get(Position, p.id)
        add_entry(first, p1, body, version_id=version)  # trava a operação até o commit
        second.execute(text("SET lock_timeout = '500ms'"))
        p2 = second.get(Position, p.id)
        with pytest.raises(DBAPIError, match="lock"):
            add_entry(second, p2, body, version_id=version)
        second.rollback()
        first.commit()
        with pytest.raises(LedgerError, match="sem quantidade em aberto"):
            add_entry(second, second.get(Position, p.id), body, version_id=version)
        second.rollback()
    finally:
        first.close()
        second.close()

    # Livro inconsistente gravado (só o dono do banco conseguiria): as leituras seguem com o aviso.
    s.add(
        PositionEntry(
            position_id=p.id, user_id=FIXED_USER_ID, kind="exit", instrument="PETRX44", series_id=None,
            quantity=100, price=Decimal("1.5"), fees_brl=Decimal(0), brokerage_brl=Decimal(0),
            executed_at=datetime(2026, 11, 19, 19, 30, tzinfo=UTC),
        )
    )  # fmt: skip
    s.commit()
    listed = api_client.get("/positions")
    assert listed.status_code == 200 and "sem quantidade" in listed.json()[0]["ledger_error"]
    assert api_client.get(f"/positions/{p.id}").status_code == 200
    port = api_client.get("/portfolio").json()
    assert port["positions_open"] == 0 and any("inconsistentes" in w for w in port["warnings"])
    MarksComputer(s, user_id=FIXED_USER_ID).run(None)  # não levanta
