"""Gestão da operação com as fixtures reais (PRD 1.11 §5.10 e §10.2; BRD 1.8 RN-GES-01..07, RS-07).

PETR4 nas fixtures: straddle de dez/26 (PETRL44 call e PETRX44 put), entrada em 17/11/2026 gravada
direto no banco (como no teste do diário), marcação até 19/11. O modelo do edge passa a `combination`
(o EWMA tem 7 de 8 janelas nas fixtures). Sinal das fixtures: edge de **compra** de vol, então o
straddle vendido perdeu o edge e o comprado ainda tem.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from tests.integration.test_forecast import forecasted  # noqa: F401
from tests.integration.test_journal import _short_straddle
from vollab.analytics.journal import JOB_KIND as MARKS_JOB
from vollab.analytics.journal import run_marks_job
from vollab.analytics.management import JOB_KIND as ALERTS_JOB
from vollab.analytics.management import AlertsEvaluator, run_alerts_job
from vollab.analytics.simulation import SimulationComputer
from vollab.api.schemas.simulation import LegInput, SimulationRequest
from vollab.collection.params import ensure_config_version
from vollab.db.config_store import create_config_version
from vollab.db.models import (
    FIXED_USER_ID,
    Alert,
    CorporateAction,
    Job,
    JobStatus,
    OptionSeries,
    Position,
    PositionEntry,
    PositionManagement,
    SeriesAdjustment,
)

pytestmark = pytest.mark.integration
AT_19 = "2026-11-19T18:00:00+00:00"


def _config(s: Session, **blocks: dict[str, Any]) -> int:
    """Versão nova com os blocos alterados (como o `POST /config`)."""
    v = ensure_config_version(s, user_id=FIXED_USER_ID)
    params = dict(v.params)
    for name, changes in blocks.items():
        params[name] = dict(params[name]) | changes
    created = create_config_version(s, user_id=FIXED_USER_ID, params=params, note="teste")
    s.commit()
    return created.id


def _run_jobs(s: Session) -> None:
    """Marcação e, depois dela, a avaliação das regras (a ordem do worker)."""
    for kind, fn in ((MARKS_JOB, run_marks_job), (ALERTS_JOB, run_alerts_job)):
        for job in s.scalars(select(Job).where(Job.kind == kind, Job.status == JobStatus.QUEUED)).all():
            fn(s, dict(job.payload))
            job.status = JobStatus.SUCCEEDED
        s.commit()


def _enqueue_marks(s: Session, *pids: int) -> None:
    from vollab.analytics.journal import enqueue_marks

    enqueue_marks(s, user_id=FIXED_USER_ID, position_ids=list(pids), reason="teste")
    s.commit()


def _copy(
    s: Session, p: Position, *, structure: str, direction: str, sign: int, expiry: date | None = None
) -> Position:
    q = Position(
        user_id=p.user_id,
        ticker=p.ticker,
        structure=structure,
        direction=direction,
        expiry=expiry or p.expiry,
        as_of=p.as_of,
        lots=p.lots,
        edge_state=p.edge_state,
        model=p.model,
        config_version_id=p.config_version_id,
        engine_version=p.engine_version,
        decision_snapshot=p.decision_snapshot,
    )
    s.add(q)
    s.flush()
    for e in s.scalars(select(PositionEntry).where(PositionEntry.position_id == p.id)).all():
        s.add(
            PositionEntry(
                position_id=q.id,
                user_id=e.user_id,
                kind="entry",
                instrument=e.instrument,
                series_id=e.series_id,
                quantity=sign * e.quantity,
                price=e.price,
                fees_brl=e.fees_brl,
                brokerage_brl=e.brokerage_brl,
                executed_at=e.executed_at,
            )
        )
    s.commit()
    return q


def _alerts(s: Session, **where: Any) -> list[Alert]:
    s.expire_all()
    stmt = select(Alert).order_by(Alert.id)
    for k, v in where.items():
        stmt = stmt.where(getattr(Alert, k) == v)
    return list(s.scalars(stmt))


def _open(s: Session, rule: str, pid: int | None) -> Alert | None:
    found = [a for a in _alerts(s, rule=rule) if a.position_id == pid and a.state != "resolved"]
    assert len(found) <= 1, "no máximo um alerta não resolvido por chave"
    return found[0] if found else None


@pytest.fixture
def managed(forecasted: Session, fixture_settings: None) -> tuple[Session, Position, Position]:  # noqa: F811
    s = forecasted
    _config(s, forecast={"selected_model": "combination"})
    short = _short_straddle(s)
    long = _copy(s, short, structure="long_straddle", direction="buy", sign=-1)
    _enqueue_marks(s, short.id, long.id)
    _run_jobs(s)
    return s, short, long


def test_rules_on_real_data_and_config_version(managed: tuple[Session, Position, Position]) -> None:
    s, short, long = managed
    version = ensure_config_version(s, user_id=FIXED_USER_ID).id
    # O job de marcação enfileira a avaliação (PRD 1.11 §5.10).
    assert (s.scalar(select(func.count()).select_from(Job).where(Job.kind == ALERTS_JOB)) or 0) >= 1

    pm = s.get(PositionManagement, short.id)
    assert pm is not None and pm.as_of == date(2026, 11, 19) and pm.config_version_id == version
    rules = {r["rule"]: r for r in pm.rules}
    assert rules["hedge_time"]["state"] == "disabled"  # padrão desligado (QA-11)
    assert rules["exit_profit"]["state"] == rules["exit_stop"]["state"] == "disabled"
    assert rules["exit_dte"]["state"] == "ok" and rules["exit_dte"]["details"]["days_to_expiry_bd"] == 20
    assert rules["hedge_band"]["state"] == "ok"
    assert rules["hedge_band"]["details"]["half_width_shares"] == pytest.approx(10.0)  # 0,10 × 100 × 1

    # Edge da posição × cálculo à mão com os números gravados: (p − c_manter − c_fechar)/σ̂.
    e = pm.edge
    assert e is not None
    assert e["premium"] == pytest.approx(e["iv"] - e["sigma"] * (1 + e["normal_spread"]))
    by_hand = (e["premium"] - e["cost_hold_vol_pts"] - e["cost_close_vol_pts"]) / e["sigma"]
    assert e["net_relative_edge"] == pytest.approx(by_hand)
    assert e["cost_hold_vol_pts"] > 0 and e["cost_close_vol_pts"] > 0
    assert Decimal(e["cost_close_brl"]) > 0  # dinheiro em texto decimal (PRD §5.1)
    assert (
        rules["exit_edge"]["state"] == "triggered" and e["net_relative_edge"] < 0
    )  # vendido, sinal de compra

    lm = s.get(PositionManagement, long.id)
    assert lm is not None and lm.edge is not None
    le = lm.edge
    assert le["net_relative_edge"] == pytest.approx(
        (-le["premium"] - le["cost_hold_vol_pts"] - le["cost_close_vol_pts"]) / le["sigma"]
    )
    assert {r["rule"]: r["state"] for r in lm.rules}["exit_edge"] == "ok"

    edge_alert = _open(s, "exit_edge", short.id)
    assert edge_alert is not None and edge_alert.kind == "exit" and edge_alert.state == "active"
    assert edge_alert.config_version_id == edge_alert.evaluated_config_version_id == version
    assert edge_alert.triggered_as_of == date(2026, 11, 19)
    assert _open(s, "exit_edge", long.id) is None
    # Sem alerta de prazo (20 du > 5). O edge acabou: a rolagem foi avaliada, mas jan/27 não tem os
    # dois strikes do straddle com IV de referência nas fixtures.
    assert _open(s, "exit_dte", short.id) is None
    assert pm.roll is not None and pm.roll["status"] == "unavailable" and not pm.roll["suggested"]
    assert pm.roll["expiry"] == "2027-01-15" and "strikes" in pm.roll["reason"]
    assert _open(s, "roll_suggested", short.id) is None
    assert lm.roll is None  # o comprado mantém o edge: nada a rolar


def test_lifecycle_dte_config_and_idempotence(managed: tuple[Session, Position, Position]) -> None:
    s, short, _ = managed
    first = _open(s, "exit_edge", short.id)
    assert first is not None

    v30 = _config(s, management={"exit_dte_bd": 20})  # 20 du até o vencimento: dispara (≤)
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    dte = _open(s, "exit_dte", short.id)
    assert dte is not None and dte.config_version_id == v30
    assert dte.details["days_to_expiry_bd"] == 20 and dte.details["max_bd"] == 20
    # O alerta antigo continua o mesmo: a configuração do disparo fica, a da avaliação muda.
    again = _open(s, "exit_edge", short.id)
    assert again is not None and again.id == first.id
    assert again.config_version_id != v30 and again.evaluated_config_version_id == v30

    # Idempotência: a mesma rodada de novo não muda nada.
    before = [(a.id, a.state, a.details, a.last_as_of) for a in _alerts(s)]
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    assert [(a.id, a.state, a.details, a.last_as_of) for a in _alerts(s)] == before

    _config(s, management={"exit_dte_bd": 19})  # 19 < 20: deixa de valer
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    gone = s.get(Alert, dte.id)
    assert gone is not None and gone.state == "resolved" and gone.resolved_by == "auto"
    assert gone.resolution_note == "a condição deixou de valer" and not gone.persisting


def test_hedge_band_alert_resolves_after_hedge(
    managed: tuple[Session, Position, Position], api_client: TestClient
) -> None:
    """Fluxo 3 da Etapa 8: alerta de banda → visto → hedge até a borda → resolve sozinho."""
    s, short, _ = managed
    _config(s, simulation={"delta_band": 0.01})  # meia-largura de 1 ação
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    band = _open(s, "hedge_band", short.id)
    assert band is not None
    delta, half = band.details["delta_shares"], band.details["half_width_shares"]
    assert abs(delta) > half == pytest.approx(1.0)
    adjust = band.details["adjust_shares"]
    assert abs(delta + adjust) <= half and adjust != 0  # leva até a borda (H1)

    r = api_client.patch(f"/alerts/{band.id}", json={"state": "seen"})
    assert r.status_code == 200 and r.json()["state"] == "seen"
    assert api_client.patch(f"/alerts/{band.id}", json={"state": "seen"}).status_code == 422

    hedge = {
        "kind": "hedge",
        "instrument": "PETR4",
        "quantity": adjust,
        "price_brl": "42.67",
        "fees_brl": "0.05",
        "brokerage_brl": "0",
        "executed_at": AT_19,
    }
    assert api_client.post(f"/positions/{short.id}/entries", json=hedge).status_code == 201
    _run_jobs(s)
    done = s.get(Alert, band.id)
    assert done is not None and done.state == "resolved" and done.resolved_by == "auto"
    assert _open(s, "hedge_band", short.id) is None


def test_user_resolution_holds_until_condition_clears(
    managed: tuple[Session, Position, Position], api_client: TestClient
) -> None:
    s, short, _ = managed
    alert = _open(s, "exit_edge", short.id)
    assert alert is not None
    r = api_client.patch(f"/alerts/{alert.id}", json={"state": "resolved", "note": "  vou manter  "})
    assert r.status_code == 200
    body = r.json()
    assert (
        body["state"] == "resolved"
        and body["resolved_by"] == "user"
        and body["resolution_note"] == "vou manter"
    )
    assert api_client.patch(f"/alerts/{alert.id}", json={"state": "seen"}).status_code == 409
    assert api_client.patch("/alerts/999999", json={"state": "seen"}).status_code == 404
    assert api_client.patch(f"/alerts/{alert.id}", json={"state": "active"}).status_code == 422

    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()  # a condição continua: não reabre
    assert _open(s, "exit_edge", short.id) is None
    held = s.get(Alert, alert.id)
    assert held is not None and held.persisting

    # A condição some (modelo sem avaliação → regra indisponível, não dispara): libera a chave.
    _config(s, forecast={"selected_model": "ewma"})
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    s.expire_all()
    assert not s.get(Alert, alert.id).persisting  # type: ignore[union-attr]
    _config(s, forecast={"selected_model": "combination"})
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    reopened = _open(s, "exit_edge", short.id)
    assert reopened is not None and reopened.id != alert.id


def test_dividend_and_strike_adjustment(
    managed: tuple[Session, Position, Position], api_client: TestClient
) -> None:
    s, short, _ = managed
    # t = 19/11; 20/11 sem pregão: 5 du = 23..27/11. Data ex em 27/11 dispara; em 30/11 (6º) não.
    for ex, amount in ((date(2026, 11, 27), "0.50"), (date(2026, 11, 30), "0.40")):
        s.add(
            CorporateAction(
                ticker="PETR4",
                ex_date=ex,
                amount=Decimal(amount),
                kind="dividend",
                source="manual",
                confirmed=True,
            )
        )
    call = s.scalar(select(OptionSeries).where(OptionSeries.code == "PETRL44"))
    assert call is not None
    s.add(
        SeriesAdjustment(
            series_id=call.id,
            effective_date=date(2026, 11, 19),
            previous_date=date(2026, 11, 18),
            old_strike=Decimal("44.00"),
            new_strike=Decimal("43.50"),
        )
    )
    s.commit()
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    divs = [a for a in _alerts(s, rule="dividend_upcoming") if a.position_id == short.id]
    assert [a.scope_key for a in divs] == ["2026-11-27"]
    assert (
        Decimal(divs[0].details["items"][0]["amount_brl"]) == Decimal("0.50")
        and divs[0].details["days_to_ex_bd"] == 5
    )
    pending = _open(s, "strike_adjustment_pending", short.id)
    assert pending is not None and pending.scope_key == "PETRL44:2026-11-19"

    adj = {
        "kind": "strike_adjustment",
        "instrument": "PETRL44",
        "quantity": -100,
        "price_brl": "0",
        "strike_after_brl": "43.50",
        "fees_brl": "0",
        "brokerage_brl": "0",
        "executed_at": AT_19,
    }
    r = api_client.post(f"/positions/{short.id}/entries", json=adj)
    assert r.status_code == 201, r.text
    _run_jobs(s)
    assert _open(s, "strike_adjustment_pending", short.id) is None
    assert s.get(Alert, pending.id).state == "resolved"  # type: ignore[union-attr]

    # Estornar o ajuste reabre a pendência (alerta novo).
    entry_id = next(e["id"] for e in r.json()["entries"] if e["kind"] == "strike_adjustment")
    void = {
        "kind": "void",
        "linked_entry_id": entry_id,
        "void_reason": "lançado errado",
        "executed_at": AT_19,
    }
    assert api_client.post(f"/positions/{short.id}/entries", json=void).status_code == 201
    _run_jobs(s)
    again = _open(s, "strike_adjustment_pending", short.id)
    assert again is not None and again.id != pending.id


def _close(api: TestClient, pid: int, quantities: dict[str, int]) -> None:
    for code, q in quantities.items():
        exit_ = {
            "kind": "exit",
            "instrument": code,
            "quantity": q,
            "price_brl": "1.00",
            "fees_brl": "0",
            "brokerage_brl": "0",
            "executed_at": AT_19,
        }
        r = api.post(f"/positions/{pid}/entries", json=exit_)
        assert r.status_code == 201, r.text


def test_limits_and_closed_position(
    managed: tuple[Session, Position, Position], api_client: TestClient
) -> None:
    s, short, long = managed
    assert _open(s, "exit_edge", short.id) is not None
    long_alerts = [a.id for a in _alerts(s) if a.position_id == long.id]
    # Encerrar o comprado (que anulava o vendido na carteira) resolve os alertas dele, com o motivo,
    # e apaga o estado derivado.
    _config(s, management={"exit_dte_bd": 20})
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    long_alerts = [a.id for a in _alerts(s) if a.position_id == long.id]
    assert long_alerts  # exit_dte do comprado
    _close(api_client, long.id, {"PETRL44": -100, "PETRX44": -100})
    _run_jobs(s)
    closed = [a for a in _alerts(s) if a.position_id == long.id]
    assert closed and all(a.state == "resolved" for a in closed)
    assert {a.resolution_note for a in closed} == {"operação encerrada"}
    assert s.get(PositionManagement, long.id) is None
    assert _open(s, "exit_edge", short.id) is not None  # o vendido segue com os dele

    _config(s, sizing={"capital_brl": 100.0})
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    limit = _open(s, "limit_stress", None)
    assert limit is not None and limit.kind == "limit" and limit.position_id is None
    assert limit.details["value"] > limit.details["limit_value"] == pytest.approx(0.20)

    body = api_client.get("/alerts").json()
    assert body["counts"]["active"] == len(body["alerts"]) and all(
        a["state"] != "resolved" for a in body["alerts"]
    )
    assert body["counts"]["resolved"] == len(closed)
    only = api_client.get("/alerts", params={"kind": "limit"}).json()["alerts"]
    assert only and all(a["kind"] == "limit" and a["ticker"] is None for a in only)
    mine = api_client.get("/alerts", params={"position_id": short.id}).json()["alerts"]
    assert mine and all(a["position_id"] == short.id and a["ticker"] == "PETR4" for a in mine)
    assert api_client.get("/alerts", params={"state": "bogus"}).status_code == 422
    history = api_client.get("/alerts", params={"state": "resolved"}).json()["alerts"]
    assert {a["id"] for a in history} == {a.id for a in closed}

    detail = api_client.get(f"/positions/{short.id}").json()
    assert detail["management"]["as_of"] == "2026-11-19"
    assert {r["rule"] for r in detail["management"]["rules"]} >= {"hedge_band", "exit_edge", "exit_dte"}
    assert detail["management"]["edge"]["net_relative_edge"] < 0
    assert {a["rule"] for a in detail["management"]["alerts"]} >= {"exit_edge", "exit_dte"}

    # Sem capital: limites indisponíveis; o alerta de limite resolve.
    _config(s, sizing={"capital_brl": None})
    AlertsEvaluator(s, user_id=FIXED_USER_ID).run()
    assert _open(s, "limit_stress", None) is None


def test_roll_needs_net_edge_after_closing_costs(forecasted: Session, fixture_settings: None) -> None:  # noqa: F811
    """RN-GES-04: o destino com edge sem o custo de fechar perde o edge quando ele entra."""
    s = forecasted
    _config(s, forecast={"selected_model": "combination"})
    sc = SimulationComputer(s, user_id=FIXED_USER_ID)
    chain = sc.chain("PETR4", date(2026, 12, 18))
    req = SimulationRequest(
        ticker="PETR4",
        structure="long_straddle",
        legs=[LegInput(series_id=i) for i in chain.suggestions["long_straddle"]],
    )
    free = sc.structure_edge(req)
    assert free.state == "edge" and free.signal_direction is not None and free.signal_direction.value == "buy"
    assert free.extra_cost_vol_pts == 0
    # Custo de fechar grande o bastante para consumir o edge: deixa de ser "edge líquido".
    assert free.p_high is not None and free.cost_buy is not None
    margin = -free.p_high - free.cost_buy  # folga até o nível exigido, em pontos
    costly = sc.structure_edge(req, extra_cost_brl_unit=(margin + 0.02) * free.vega_unit)
    assert costly.state != "edge"
    assert costly.cost_buy == pytest.approx(free.cost_buy + margin + 0.02)


def test_roll_suggested_end_to_end(forecasted: Session, fixture_settings: None) -> None:  # noqa: F811
    """Rolagem sugerida: a posição "vence" antes de dez/26 (vencimento do registro trocado só no teste),
    o 1º vencimento depois dele com ≥ 10 du é dez/26 (20 du) e o straddle comprado tem edge de compra."""
    s = forecasted
    _config(s, forecast={"selected_model": "combination"}, management={"exit_dte_bd": 20})
    short = _short_straddle(s)
    long = _copy(s, short, structure="long_straddle", direction="buy", sign=-1, expiry=date(2026, 11, 27))
    _enqueue_marks(s, long.id)
    _run_jobs(s)
    roll = _open(s, "roll_suggested", long.id)
    assert roll is not None and roll.kind == "roll"
    d = roll.details
    assert d["suggested"] and d["expiry"] == "2026-12-18" and d["horizon_bd"] >= 10
    assert d["state"] == "edge" and d["signal_direction"] == "buy" and d["lots"] == 1
    assert len(d["legs"]) == 2 and Decimal(d["close_cost_brl"]) > 0 and d["close_cost_vol_pts"] > 0
    pm = s.get(PositionManagement, long.id)
    assert pm is not None and pm.roll is not None and pm.roll["suggested"]

    # Covered call (venda) com o mesmo prazo: rolagem avaliada, sem edge na direção.
    cc = _copy(s, short, structure="covered_call", direction="sell", sign=1)
    _enqueue_marks(s, cc.id)
    _run_jobs(s)
    assert _open(s, "roll_suggested", cc.id) is None
    rules = {r["rule"]: r for r in s.get(PositionManagement, cc.id).rules}  # type: ignore[union-attr]
    assert rules["roll_suggested"]["state"] in ("ok", "unavailable")
    assert rules["roll_suggested"]["details"]["suggested"] is False


def test_alerts_table_guarded_for_app_role(
    managed: tuple[Session, Position, Position], owner_session: Session
) -> None:
    s, short, _ = managed
    alert = _open(s, "exit_edge", short.id)
    assert alert is not None
    for sql in (
        "DELETE FROM alerts WHERE id = :i",
        "UPDATE alerts SET rule = 'exit_dte' WHERE id = :i",
        "UPDATE alerts SET config_version_id = config_version_id WHERE id = :i AND false",  # sem efeito
        "UPDATE alerts SET triggered_as_of = '2026-01-01' WHERE id = :i",
    ):
        try:
            s.execute(text(sql), {"i": alert.id})
            s.flush()
            ok = "AND false" in sql
        except (DBAPIError, ProgrammingError):
            ok = False
        s.rollback()
        assert ok == ("AND false" in sql), sql
    # Resolvido: imutável, exceto `persisting` de verdadeiro para falso.
    s.execute(
        text(
            "UPDATE alerts SET state = 'resolved', resolved_at = now(), resolved_by = 'user', "
            "persisting = true WHERE id = :i"
        ),
        {"i": alert.id},
    )
    s.commit()
    with pytest.raises(DBAPIError):
        s.execute(text("UPDATE alerts SET resolution_note = 'x' WHERE id = :i"), {"i": alert.id})
        s.flush()
    s.rollback()
    with pytest.raises(DBAPIError):
        s.execute(text("UPDATE alerts SET state = 'active' WHERE id = :i"), {"i": alert.id})
        s.flush()
    s.rollback()
    s.execute(text("UPDATE alerts SET persisting = false WHERE id = :i"), {"i": alert.id})
    s.commit()
    with pytest.raises(DBAPIError):
        s.execute(text("UPDATE alerts SET persisting = true WHERE id = :i"), {"i": alert.id})
        s.flush()
    s.rollback()
    # Nem o dono apaga (trigger), mesmo sem passar pelos privilégios.
    with pytest.raises(DBAPIError):
        owner_session.execute(text("DELETE FROM alerts WHERE id = :i"), {"i": alert.id})
        owner_session.flush()
    owner_session.rollback()
