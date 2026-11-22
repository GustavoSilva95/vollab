"""Coleta de ponta a ponta com fixtures reais (PRD §9 M1, §10.1, PRD-NF-03).

Fonte simulada por `FixtureSources`; nenhum acesso à rede.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from tests.conftest import FIXTURES
from vollab.collection.runner import ActiveRunError, Collector, create_run
from vollab.data.http import TransientSourceError
from vollab.data.raw_cache import RawCache
from vollab.data.sources import Fetched, FixtureSources
from vollab.db.models import (
    FIXED_USER_ID,
    CollectionItem,
    CollectionRun,
    CorporateAction,
    DailyBar,
    OptionSeries,
    RawFile,
    RiskFreeRate,
    trades,
)
from vollab.jobs.control import JobInterruptedError
from vollab.settings import Settings

pytestmark = pytest.mark.integration

TODAY = date(2026, 11, 20)  # D-1 = 19/11/2026, último pregão das fixtures


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://u:p@127.0.0.1:5432/x_test",
        data_source="fixtures",
        fixtures_dir=FIXTURES,
        collection_today=TODAY,
        raw_data_dir=tmp_path / "raw",
    )


def _collector(
    session: Session,
    tmp_path: Path,
    *,
    sources: object | None = None,
    stop: Callable[[], bool] = lambda: False,
) -> Collector:
    settings = _settings(tmp_path)
    return Collector(
        session,
        sources=sources or FixtureSources(FIXTURES),  # type: ignore[arg-type]
        cache=RawCache(settings.raw_data_dir),
        settings=settings,
        stop=stop,
    )


def _run(session: Session, tmp_path: Path, **kwargs: object) -> CollectionRun:
    run = create_run(session, user_id=FIXED_USER_ID, settings=_settings(tmp_path))
    _collector(session, tmp_path, **kwargs).execute(run)  # type: ignore[arg-type]
    session.refresh(run)
    return run


def _snapshot(session: Session) -> dict[str, object]:
    """Estado gravado, para comparar execuções (idempotência)."""
    return {
        "trades": session.execute(
            text(
                "SELECT count(*), sum(quantity), sum(price * quantity), count(*) FILTER (WHERE r4_valid) "
                "FROM trades"
            )
        ).one(),
        "bars": session.execute(
            text("SELECT ticker, trade_date, close, trades_count, r4_check FROM daily_bars ORDER BY 1, 2")
        ).all(),
        "series": session.execute(
            text("SELECT code, expiry, strike, style FROM option_series ORDER BY 1, 2")
        ).all(),
        "stats": session.scalar(text("SELECT count(*) FROM option_daily_stats")),
        "rates": session.execute(text("SELECT day, rate FROM risk_free_rates ORDER BY 1")).all(),
        "actions": session.execute(
            text("SELECT ticker, ex_date, amount, source FROM corporate_actions ORDER BY 1, 2, 4")
        ).all(),
    }


def test_full_collection_from_fixtures(session: Session, tmp_path: Path) -> None:
    run = _run(session, tmp_path)
    assert run.origin == "initial_load"
    # Fixtures cobrem só parte da janela: o resto falha com 404 e entra no relatório de lacunas.
    assert run.status == "partial"

    # OHLC oficial do anual (recorte) e do diário; a R4 confere com ele nos 11 pregões de PETR4.
    checks = dict(
        session.execute(
            select(DailyBar.trade_date, DailyBar.r4_check).where(
                DailyBar.ticker == "PETR4", DailyBar.trade_date >= date(2026, 11, 5)
            )
        ).all()
    )
    assert len(checks) == 11
    assert set(checks.values()) == {"ok"}
    bar = session.get(DailyBar, ("PETR4", date(2026, 11, 19)))
    assert bar is not None and bar.source == "b3_cotahist_daily" and bar.close == Decimal("42.67")
    older = session.get(DailyBar, ("PETR4", date(2026, 3, 2)))
    assert older is not None and older.source == "b3_cotahist_annual"

    # Negócios: R4 calculada na gravação, IDs repetidos de D-1 preservados como linhas distintas.
    n_valid = session.scalar(
        select(func.count())
        .select_from(trades)
        .where(
            trades.c.instrument == "PETR4", trades.c.reference_date == date(2026, 11, 18), trades.c.r4_valid
        )
    )
    assert n_valid == 53871

    # Séries pelo ISIN, com estilo inferido (RN-DAD-02).
    l44 = session.scalar(select(OptionSeries).where(OptionSeries.code == "PETRL44"))
    assert l44 is not None
    assert (l44.underlying_isin, l44.style, l44.expiry) == ("BRPETRACNPR6", "european", date(2026, 12, 18))

    # Pré-filtro: PETRL44 (K/S ≈ 1,01, 1º vencimento, 639 negócios) foi pedida e gravada.
    item = session.scalar(
        select(CollectionItem).where(
            CollectionItem.key == "PETRL44", CollectionItem.trade_date == date(2026, 11, 19)
        )
    )
    assert item is not None and item.status == "ok" and item.underlying == "PETR4"
    options = session.scalars(
        select(CollectionItem.key).where(
            CollectionItem.run_id == run.id,
            CollectionItem.phase == 4,
            CollectionItem.trade_date == date(2026, 11, 19),
        )
    ).all()
    assert 50 < len(options) < 400  # Etapa 0: ~280 séries elegíveis por pregão no universo
    assert all(not k.endswith(("W1", "W2", "W3", "W4", "W5")) for k in options)

    # Selic em decimal; proventos do Yahoo como estimados.
    rate = session.get(RiskFreeRate, date(2026, 11, 19))
    assert rate is not None and rate.rate == Decimal("0.1365")
    yahoo = session.scalars(select(CorporateAction).where(CorporateAction.source == "yahoo")).all()
    assert yahoo and not any(a.confirmed for a in yahoo)

    # Cache bruto preservado, endereçado por hash e conferido.
    raw = session.scalars(select(RawFile)).all()
    assert raw and all((tmp_path / "raw" / r.relative_path).is_file() for r in raw)


def test_collection_is_idempotent_and_reprocessing_gives_same_state(session: Session, tmp_path: Path) -> None:
    """PRD-NF-03 e PRD §9 M1: reexecutar não duplica; reprocessar do cache gera o mesmo estado."""
    _run(session, tmp_path)
    first = _snapshot(session)
    second_run = _run(session, tmp_path)
    assert second_run.origin == "manual"
    # Só voltam itens com falha não permanente; o que já foi gravado não é pedido de novo.
    retried = session.scalars(
        select(CollectionItem.status).where(CollectionItem.run_id == second_run.id)
    ).all()
    assert "ok" not in retried
    assert _snapshot(session) == first

    # Reprocessar a partir de data/raw/: apaga os dados de mercado e regrava a partir do cache.
    from vollab.collection import ingest

    universe = ingest.load_universe(session)
    cache = RawCache(tmp_path / "raw")
    ok_items = session.execute(
        select(CollectionItem, RawFile)
        .join(RawFile, RawFile.id == CollectionItem.raw_file_id)
        .where(CollectionItem.status.in_(("ok", "empty")))
        .order_by(CollectionItem.phase, CollectionItem.id)
    )
    session.execute(
        text(
            "TRUNCATE trades, daily_bars, option_daily_stats, series_adjustments, risk_free_rates, "
            "corporate_actions"
        )
    )
    session.execute(text("DELETE FROM option_series"))
    for item, raw in ok_items:
        content = cache.read(raw.relative_path, expected_sha256=raw.sha256)
        if item.source == "b3_trades":
            ingest.ingest_trades(
                session, content=content, raw_file_id=raw.id, ticker=item.key, day=item.trade_date,
                is_underlying=item.phase != 4,
            )  # fmt: skip
        elif item.source.startswith("b3_cotahist"):
            ingest.ingest_cotahist(
                session,
                content=content,
                raw_file_id=raw.id,
                annual=item.source.endswith("annual"),
                universe=universe,
            )
        elif item.source == "bcb_selic":
            ingest.ingest_selic(session, content=content, raw_file_id=raw.id)
        else:
            ingest.ingest_dividends(session, content=content, raw_file_id=raw.id, ticker=item.key)
    session.commit()
    assert _snapshot(session) == first


def test_interrupted_collection_resumes_from_next_item(session: Session, tmp_path: Path) -> None:
    """PRD-NF-03: parar o worker no meio e retomar dá o mesmo resultado de uma execução contínua."""
    run = create_run(session, user_id=FIXED_USER_ID, settings=_settings(tmp_path))
    calls = {"n": 0}

    def stop_after_40() -> bool:
        calls["n"] += 1
        return calls["n"] > 40

    with pytest.raises(JobInterruptedError):
        _collector(session, tmp_path, stop=stop_after_40).execute(run)
    session.rollback()
    done = session.scalar(
        select(func.count()).select_from(CollectionItem).where(CollectionItem.status != "pending")
    )
    assert done == 40
    session.refresh(run)
    assert run.status == "running"
    _collector(session, tmp_path).execute(run)
    session.refresh(run)
    assert run.status == "partial"
    # Nenhum item processado duas vezes.
    assert session.scalar(select(func.max(CollectionItem.attempts))) == 1


class _Down(FixtureSources):
    def cotahist_annual(self, year: int) -> Fetched:
        raise TransientSourceError("HTTP 503")

    def cotahist_daily(self, day: date) -> Fetched:
        raise TransientSourceError("HTTP 503")


def test_consecutive_transient_failures_interrupt_run(session: Session, tmp_path: Path) -> None:
    run = _run(session, tmp_path, sources=_Down(FIXTURES))
    assert run.status == "interrupted"
    assert run.message is not None and "falhas seguidas" in run.message
    failed = session.scalars(select(CollectionItem).where(CollectionItem.status == "failed")).all()
    assert len(failed) == 5
    assert all(not i.permanent and "503" in (i.error or "") for i in failed)
    # Os itens que não chegaram a ser tentados continuam pendentes para a próxima execução.
    assert session.scalar(
        select(func.count()).select_from(CollectionItem).where(CollectionItem.status == "pending")
    )


def test_only_one_active_run(session: Session, tmp_path: Path) -> None:
    create_run(session, user_id=FIXED_USER_ID, settings=_settings(tmp_path))
    with pytest.raises(ActiveRunError):
        create_run(session, user_id=FIXED_USER_ID, settings=_settings(tmp_path))


def test_holiday_empty_file_is_recorded_as_empty(session: Session, tmp_path: Path) -> None:
    """RF-DAD-03: ZIP só com cabeçalho → `vazio`."""
    from vollab.collection import ingest

    content = (FIXTURES / "b3/rapinegocios/PETR4_2026-11-20.zip").read_bytes()
    raw = RawFile(
        source="b3_trades", query_key="PETR4", query_date=date(2026, 11, 20), relative_path="x", sha256="0",
        size_bytes=len(content), http_status=200, content_format="zip",
    )  # fmt: skip
    session.add(raw)
    session.flush()
    result = ingest.ingest_trades(
        session,
        content=content,
        raw_file_id=raw.id,
        ticker="PETR4",
        day=date(2026, 11, 20),
        is_underlying=True,
    )
    assert result.empty and result.rows == 0
