"""Recálculo de volatilidade no worker com as fixtures reais (PRD §5.5, §9 M1 Vol, PRD-NF-06).

Coleta com a fonte simulada (hoje = 20/11/2026) e roda o job `vol_recompute` enfileirado ao fim.
"""

import itertools
import math
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.conftest import FIXTURES
from vollab.analytics.recompute import JOB_KIND, run_recompute_job
from vollab.collection.runner import Collector, create_run
from vollab.data.raw_cache import RawCache
from vollab.data.sources import FixtureSources
from vollab.db.models import (
    FIXED_USER_ID,
    AtmTermPoint,
    ConstantMaturityVol,
    DailyBar,
    ImpliedVol,
    IntradayBar,
    IntradaySession,
    Job,
    OptionDailyQuote,
    RealizedVol,
)
from vollab.quant.pricing import IvStatus
from vollab.settings import Settings

pytestmark = pytest.mark.integration

TODAY = date(2026, 11, 20)


def _collect(session: Session, tmp_path: Path) -> None:
    settings = Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5432/x_test",
        data_source="fixtures",
        fixtures_dir=FIXTURES,
        collection_today=TODAY,
        raw_data_dir=tmp_path / "raw",
    )
    run = create_run(session, user_id=FIXED_USER_ID, settings=settings)
    Collector(
        session, sources=FixtureSources(FIXTURES), cache=RawCache(settings.raw_data_dir), settings=settings
    ).execute(run)


def _recompute(session: Session) -> Job:
    job = session.scalars(select(Job).where(Job.kind == JOB_KIND).order_by(Job.id.desc())).first()
    assert job is not None, "a coleta deve enfileirar o recálculo"
    run_recompute_job(session, dict(job.payload))
    return job


def _state(session: Session) -> dict[str, object]:
    return {
        name: session.execute(text(sql)).all()
        for name, sql in {
            "sessions": "SELECT ticker, trade_date, bars_with_trades, intraday_variance "
            "FROM intraday_sessions ORDER BY 1, 2",
            "rv": "SELECT ticker, as_of, estimator, window_bd, vol FROM realized_vols ORDER BY 1, 2, 3, 4",
            "iv": "SELECT series_id, trade_date, trade_id, iv, iv_status FROM implied_vols ORDER BY 1, 2, 3",
            "quotes": "SELECT series_id, trade_date, iv, status FROM option_daily_quotes ORDER BY 1, 2",
            "atm": "SELECT ticker, as_of, expiry, atm_iv FROM atm_term_structure ORDER BY 1, 2, 3",
            "cm": "SELECT ticker, as_of, iv, fallback_iv FROM constant_maturity_vols ORDER BY 1, 2",
        }.items()
    }


@pytest.fixture
def recomputed(session: Session, tmp_path: Path) -> Session:
    _collect(session, tmp_path)
    _recompute(session)
    return session


def test_intraday_sessions_from_real_trades(recomputed: Session) -> None:
    s = recomputed
    sessions = s.scalars(
        select(IntradaySession).where(IntradaySession.ticker == "PETR4").order_by(IntradaySession.trade_date)
    ).all()
    # 11 pregões com negócios do PETR4 nas fixtures (05/11 a 19/11).
    assert sessions[0].trade_date == date(2026, 11, 5)
    assert len(sessions) == 11
    for x in sessions:
        assert x.session_open.hour == 10 and x.session_close.hour == 18
        assert x.bars_total == 96
        assert x.complete, (x.trade_date, x.coverage)
        assert 0 < x.intraday_variance < 0.01
    bars = s.scalar(select(func.count()).select_from(IntradayBar).where(IntradayBar.ticker == "PETR4"))
    assert bars == 11 * 96


def test_realized_vols_match_daily_bars(recomputed: Session) -> None:
    s = recomputed
    bars = s.execute(
        select(DailyBar.trade_date, DailyBar.close)
        .where(DailyBar.ticker == "PETR4")
        .order_by(DailyBar.trade_date)
    ).all()
    last = bars[-1][0]
    row = s.get(RealizedVol, ("PETR4", last, "close_to_close", 20))
    assert row is not None
    # Fixtures: o anual é um recorte (não tem todos os pregões) → a janela pode ficar incompleta.
    closes = {d: float(c) for d, c in bars}
    days = sorted(closes)[-21:]
    consecutive = all((b - a).days <= 4 for a, b in itertools.pairwise(days))  # sem buracos grandes
    if row.status == "ok":
        rets = np.diff(np.log([closes[d] for d in days]))
        assert consecutive
        assert row.variance_annual == pytest.approx(np.mean(rets**2) * 252, rel=1e-12)
    else:
        assert row.reason == "missing_days"
        assert row.vol is None
    statuses = set(s.scalars(select(RealizedVol.status).where(RealizedVol.ticker == "PETR4")))
    assert "ok" in statuses
    # Intradiária: 11 pregões < janela de 20 → dados insuficientes, nunca um número.
    intraday = s.get(RealizedVol, ("PETR4", date(2026, 11, 19), "intraday_5m", 20))
    assert intraday is not None and intraday.status == "insufficient_data" and intraday.vol is None


def test_implied_vols_synchronized_and_reference(recomputed: Session) -> None:
    s = recomputed
    ivs = s.scalars(select(ImpliedVol)).all()
    assert ivs, "deve haver IV por negócio nas séries de PETR4 das fixtures"
    ok = [x for x in ivs if x.iv_status == IvStatus.OK]
    assert len(ok) / len(ivs) > 0.9
    assert all(x.lag_ms <= 10_000 for x in ivs)
    assert all(0.05 < (x.iv or 0) < 3.0 for x in ok)
    quotes = s.scalars(select(OptionDailyQuote)).all()
    assert quotes
    for q in quotes:
        assert q.trades_synced + q.trades_lag_discarded == q.trades_valid
        if q.status == "ok":
            assert q.trades_used >= 3 and q.iv is not None and q.implied_price is not None
        elif q.status == "low_sample":
            assert q.trades_used == 1 and q.iv is not None
        else:
            assert q.iv is None


def test_term_structure_rows(recomputed: Session) -> None:
    s = recomputed
    atm = s.scalars(select(AtmTermPoint)).all()
    cm = s.scalars(select(ConstantMaturityVol)).all()
    assert atm and cm
    for p in atm:
        assert (p.status == "ok") == (p.atm_iv is not None)
        assert p.forward > 0
    for c in cm:
        assert (c.status == "ok") == (c.iv is not None)
        if c.status == "unavailable":
            assert c.reason
            assert c.iv is None
            assert c.fallback_iv is None or math.isfinite(c.fallback_iv)


def test_recompute_is_idempotent(recomputed: Session) -> None:
    before = _state(recomputed)
    _recompute(recomputed)
    assert _state(recomputed) == before
    # Recálculo completo também reproduz o mesmo estado.
    run_recompute_job(recomputed, {"user_id": str(FIXED_USER_ID), "full": True})
    assert _state(recomputed) == before


def test_second_job_has_nothing_to_redo(recomputed: Session) -> None:
    """Revisão de performance da Etapa 3: sem pedidos novos, nenhum pregão volta ao escopo."""
    from vollab.analytics.params import VolParams
    from vollab.analytics.recompute import Recomputer
    from vollab.collection.params import CollectionParams
    from vollab.collection.planner import PHASE_OPTIONS, PHASE_UNDERLYING

    r = Recomputer(recomputed, version_id=1, vol=VolParams(), collection=CollectionParams())
    for phase in (PHASE_UNDERLYING, PHASE_OPTIONS):
        assert r._scope("PETR4", set(), False, phase=phase) == []


def test_dividend_recompute_is_deduplicated_and_skips_intraday(recomputed: Session) -> None:
    from vollab.analytics.recompute import enqueue_recompute

    for _ in range(3):
        enqueue_recompute(
            recomputed, user_id=FIXED_USER_ID, tickers=["PETR4"], full=True, skip_intraday=True, reason="x"
        )
    recomputed.commit()
    queued = recomputed.scalars(
        select(Job).where(
            Job.kind == JOB_KIND, Job.status == "queued", Job.payload["skip_intraday"].as_boolean()
        )
    ).all()
    assert len(queued) == 1
    computed_before = recomputed.scalars(select(IntradaySession.computed_at)).all()
    run_recompute_job(recomputed, dict(queued[0].payload))
    assert recomputed.scalars(select(IntradaySession.computed_at)).all() == computed_before
