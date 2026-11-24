"""Gravação no banco do que foi baixado (PRD §6, RN-DAD-01..03).

Cada função recebe o conteúdo bruto já preservado em `data/raw/` e é **idempotente**:
reprocessar o mesmo arquivo produz o mesmo estado (PRD §9 M1, PRD-NF-03).
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, cast

import psycopg
from sqlalchemy import case, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from vollab.data.b3_cotahist import (
    CotahistParseError,
    CotahistRecord,
    RecordFilter,
    infer_style,
    read_cotahist,
)
from vollab.data.b3_trades import TradeRow, parse_trades, r4_filter, r4_mask, reconstruct_ohlc
from vollab.data.bcb import SELIC_SERIES, parse_sgs
from vollab.data.yahoo import parse_dividends
from vollab.db.models import (
    CorporateAction,
    DailyBar,
    OptionDailyStat,
    OptionSeries,
    RiskFreeRate,
    SeriesAdjustment,
    Underlying,
    trades,
)

# Linhas por INSERT: mantém o número de parâmetros bem abaixo do limite do Postgres (65.535).
_BATCH = 2000

_TRADE_COLUMNS = (
    "reference_date",
    "instrument",
    "trade_date",
    "trade_id",
    "update_action",
    "price",
    "quantity",
    "traded_at",
    "session_type",
    "buyer",
    "seller",
    "r4_valid",
    "raw_file_id",
)


@dataclass(frozen=True)
class IngestResult:
    rows: int
    empty: bool = False


@dataclass(frozen=True)
class UniverseRef:
    """Ativos-objeto conhecidos (ticker → ISIN), usados para filtrar o COTAHIST."""

    isin_by_ticker: dict[str, str | None]

    @property
    def isins(self) -> set[str]:
        return {i for i in self.isin_by_ticker.values() if i}


def load_universe(session: Session, *, active_only: bool = False) -> UniverseRef:
    """Ativos de todos os usuários: dados de mercado são compartilhados (PRD §6), então o COTAHIST
    grava OHLC e séries de qualquer ativo cadastrado."""
    stmt = select(Underlying.ticker, Underlying.isin)
    if active_only:
        stmt = stmt.where(Underlying.active.is_(True))
    return UniverseRef({t: i for t, i in session.execute(stmt)})


# --- COTAHIST -------------------------------------------------------------------------------


def _bar_values(rec: CotahistRecord, *, source: str, raw_file_id: int) -> dict[str, Any]:
    return {
        "ticker": rec.ticker,
        "trade_date": rec.trade_date,
        "isin": rec.isin,
        "open": rec.open,
        "high": rec.high,
        "low": rec.low,
        "close": rec.last,
        "avg_price": rec.avg,
        "trades_count": rec.trades_count,
        "quantity": rec.quantity,
        "volume": rec.volume,
        "source": source,
        "raw_file_id": raw_file_id,
    }


def ingest_cotahist(
    session: Session, *, content: bytes, raw_file_id: int, annual: bool, universe: UniverseRef
) -> IngestResult:
    """OHLC oficial do ativo-objeto e, no diário, o cadastro e as estatísticas das opções."""
    keep = RecordFilter(
        underlying_tickers=universe.isin_by_ticker.keys(), underlying_isins=universe.isins, options=not annual
    )
    parsed = read_cotahist(content, keep=keep, annual=annual)
    # Sem duplicatas na mesma instrução (ON CONFLICT não aceita a mesma chave duas vezes).
    bars = list({(r.ticker, r.trade_date): r for r in parsed.records if not r.is_option}.values())
    options = list({(r.ticker, r.expiry, r.trade_date): r for r in parsed.records if r.is_option}.values())

    # Completa o ISIN de ativos cadastrados sem ele (RN-DAD-02: séries pelo ISIN).
    for rec in bars:
        if universe.isin_by_ticker.get(rec.ticker) is None:
            session.execute(
                update(Underlying)
                .where(Underlying.ticker == rec.ticker, Underlying.isin.is_(None))
                .values(isin=rec.isin)
            )

    source = "b3_cotahist_annual" if annual else "b3_cotahist_daily"
    for start in range(0, len(bars), _BATCH):
        stmt = insert(DailyBar).values(
            [_bar_values(r, source=source, raw_file_id=raw_file_id) for r in bars[start : start + _BATCH]]
        )
        if annual:
            # O diário do mesmo pregão prevalece (é o que a coleta intradiária verifica).
            stmt = stmt.on_conflict_do_nothing(index_elements=["ticker", "trade_date"])
        else:
            excluded = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "trade_date"],
                set_={
                    c: excluded[c]
                    for c in _bar_values(bars[0], source="", raw_file_id=0)
                    if c not in ("ticker", "trade_date")
                },
            )
        session.execute(stmt)

    if options:
        series_ids = _upsert_series(session, options)
        _upsert_option_stats(session, options, series_ids, raw_file_id)
        refresh_adjustments(session, series_ids=set(series_ids.values()))
        refresh_strike_adjustment_actions(session, isins={r.isin for r in options}, universe=universe)
    return IngestResult(rows=len(parsed.records))


def _expiry(rec: CotahistRecord) -> date:
    if rec.expiry is None:
        raise CotahistParseError("Opção sem data de vencimento.")
    return rec.expiry


def _upsert_series(session: Session, options: Sequence[CotahistRecord]) -> dict[tuple[str, date], int]:
    latest: dict[tuple[str, date], CotahistRecord] = {}
    for rec in sorted(options, key=lambda r: r.trade_date):
        latest[(rec.ticker, _expiry(rec))] = rec
    ids: dict[tuple[str, date], int] = {}
    unique = list(latest.values())
    for start in range(0, len(unique), _BATCH):
        ids.update(_upsert_series_batch(session, unique[start : start + _BATCH]))
    return ids


def _upsert_series_batch(session: Session, options: Sequence[CotahistRecord]) -> dict[tuple[str, date], int]:
    values = []
    for rec in options:
        values.append(
            {
                "code": rec.ticker,
                "expiry": _expiry(rec),
                "underlying_isin": rec.isin,
                "option_type": rec.option_type,
                "strike": rec.strike,
                "style": infer_style(rec),
                "style_source": "name_suffix",
                "is_weekly": rec.is_weekly,
                "first_trade_date": rec.trade_date,
                "last_trade_date": rec.trade_date,
            }
        )
    stmt = insert(OptionSeries).values(values)
    ex = stmt.excluded
    upsert = stmt.on_conflict_do_update(
        index_elements=["code", "expiry"],
        set_={
            "first_trade_date": func.least(OptionSeries.first_trade_date, ex.first_trade_date),
            "last_trade_date": func.greatest(OptionSeries.last_trade_date, ex.last_trade_date),
            # Strike vigente = o do pregão mais recente observado.
            "strike": case(
                (ex.last_trade_date >= OptionSeries.last_trade_date, ex.strike), else_=OptionSeries.strike
            ),
        },
    ).returning(OptionSeries.code, OptionSeries.expiry, OptionSeries.id)
    return {(code, expiry): sid for code, expiry, sid in session.execute(upsert)}


def _upsert_option_stats(
    session: Session,
    options: Sequence[CotahistRecord],
    series_ids: dict[tuple[str, date], int],
    raw_file_id: int,
) -> None:
    values = []
    for rec in options:
        values.append(
            {
                "series_id": series_ids[(rec.ticker, _expiry(rec))],
                "trade_date": rec.trade_date,
                "strike": rec.strike,
                "open": rec.open,
                "high": rec.high,
                "low": rec.low,
                "avg_price": rec.avg,
                "last": rec.last,
                "best_bid": rec.best_bid,
                "best_ask": rec.best_ask,
                "trades_count": rec.trades_count,
                "quantity": rec.quantity,
                "volume": rec.volume,
                "raw_file_id": raw_file_id,
            }
        )
    for start in range(0, len(values), _BATCH):
        chunk = values[start : start + _BATCH]
        stmt = insert(OptionDailyStat).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["series_id", "trade_date"],
            set_={c: stmt.excluded[c] for c in chunk[0] if c not in ("series_id", "trade_date")},
        )
        session.execute(stmt)


def refresh_adjustments(session: Session, *, series_ids: Iterable[int]) -> None:
    """Recalcula os ajustes de strike das séries a partir do histórico diário (RN-DAD-03).

    Recalcular (em vez de só acrescentar) torna o resultado independente da ordem em que os
    pregões foram coletados.
    """
    ids = sorted(series_ids)
    if not ids:
        return
    session.execute(delete(SeriesAdjustment).where(SeriesAdjustment.series_id.in_(ids)))
    session.execute(
        text(
            """
            INSERT INTO series_adjustments (series_id, effective_date, previous_date, old_strike, new_strike)
            SELECT series_id, trade_date, prev_date, prev_strike, strike
            FROM (
                SELECT series_id, trade_date, strike,
                       lag(strike) OVER w AS prev_strike,
                       lag(trade_date) OVER w AS prev_date
                FROM option_daily_stats
                WHERE series_id = ANY(:ids)
                WINDOW w AS (PARTITION BY series_id ORDER BY trade_date)
            ) t
            WHERE prev_strike IS NOT NULL AND prev_strike <> strike
            """
        ),
        {"ids": ids},
    )


def refresh_strike_adjustment_actions(
    session: Session, *, isins: Iterable[str], universe: UniverseRef
) -> None:
    """Provento oficial implícito: a redução de strike mais frequente do dia (RS-02, Etapa 0 §8).

    Gravado em `corporate_actions` com fonte `b3_strike_adjustment`, para conferir o Yahoo.
    Exige ao menos 3 séries com a mesma redução no mesmo pregão.
    """
    ticker_by_isin = {i: t for t, i in universe.isin_by_ticker.items() if i}
    wanted = [i for i in isins if i in ticker_by_isin]
    if not wanted:
        return
    rows = session.execute(
        select(
            OptionSeries.underlying_isin,
            SeriesAdjustment.effective_date,
            SeriesAdjustment.old_strike,
            SeriesAdjustment.new_strike,
        )
        .join(OptionSeries, OptionSeries.id == SeriesAdjustment.series_id)
        .where(OptionSeries.underlying_isin.in_(wanted))
    )
    deltas: dict[tuple[str, date], Counter[Decimal]] = defaultdict(Counter)
    for isin, day, old, new in rows:
        if old > new:
            deltas[(isin, day)][old - new] += 1
    tickers = [ticker_by_isin[i] for i in wanted]
    session.execute(
        delete(CorporateAction).where(
            CorporateAction.source == "b3_strike_adjustment", CorporateAction.ticker.in_(tickers)
        )
    )
    values = []
    for (isin, day), counter in sorted(deltas.items()):
        amount, count = counter.most_common(1)[0]
        if count >= 3:
            values.append(
                {
                    "ticker": ticker_by_isin[isin],
                    "ex_date": day,
                    "amount": amount,
                    "kind": "unknown",
                    "source": "b3_strike_adjustment",
                    "confirmed": True,
                }
            )
    if values:
        session.execute(insert(CorporateAction).values(values))


# --- Negócios -------------------------------------------------------------------------------


def ensure_trades_partition(session: Session, day: date) -> None:
    """Cria a partição mensal de `trades` se ainda não existir (PRD-QA-02).

    Pela função `create_trades_partition` (migration 0007, `SECURITY DEFINER`): o papel da aplicação
    não tem DDL (backlog M-2 b)."""
    session.execute(text("SELECT create_trades_partition(:d)"), {"d": day})


def _dedupe(rows: Sequence[TradeRow]) -> list[TradeRow]:
    seen: set[tuple[date, int, int]] = set()
    out = []
    for r in rows:
        key = (r.trade_date, r.trade_id, r.update_action)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def ingest_trades(
    session: Session, *, content: bytes, raw_file_id: int, ticker: str, day: date, is_underlying: bool
) -> IngestResult:
    """Grava os negócios do arquivo (substitui os do mesmo ticker e pregão) e, para o ativo-objeto,
    confere o OHLC da R4 com o oficial (RN-DAD-01)."""
    rows = parse_trades(content, expected_instrument=ticker, expected_date=day)
    ensure_trades_partition(session, day)
    session.execute(delete(trades).where(trades.c.reference_date == day, trades.c.instrument == ticker))
    if not rows:
        return IngestResult(rows=0, empty=True)
    unique_rows = _dedupe(rows)
    mask = r4_mask(unique_rows)
    dbapi = cast(psycopg.Connection[Any], session.connection().connection.driver_connection)
    with dbapi.cursor() as cur, cur.copy(f"COPY trades ({', '.join(_TRADE_COLUMNS)}) FROM STDIN") as copy:
        for r, valid in zip(unique_rows, mask, strict=True):
            copy.write_row(
                (
                    r.reference_date,
                    r.instrument,
                    r.trade_date,
                    r.trade_id,
                    r.update_action,
                    r.price,
                    r.quantity,
                    r.traded_at,
                    r.session_type,
                    r.buyer,
                    r.seller,
                    valid,
                    raw_file_id,
                )
            )
    if is_underlying:
        check_daily_bar(session, ticker=ticker, day=day, rows=unique_rows)
    return IngestResult(rows=len(unique_rows))


def check_daily_bar(session: Session, *, ticker: str, day: date, rows: Sequence[TradeRow]) -> None:
    """Verificação de qualidade (RN-DAD-01): preço e nº de negócios da R4 × COTAHIST."""
    bar = session.get(DailyBar, (ticker, day))
    if bar is None:
        return
    ohlc = reconstruct_ohlc(r4_filter(rows))
    diff: list[str] = []
    if ohlc is None:
        diff = ["trades_count"]
    else:
        pairs = {
            "trades_count": (ohlc.trades_count, bar.trades_count),
            "open": (ohlc.open, bar.open),
            "high": (ohlc.high, bar.high),
            "low": (ohlc.low, bar.low),
            "close": (ohlc.close, bar.close),
        }
        diff = [k for k, (got, official) in pairs.items() if got != official]
        if abs(ohlc.vwap - bar.avg_price) > Decimal("0.01"):
            diff.append("avg_price")
    bar.r4_check = "diverged" if diff else "ok"
    bar.r4_diff = ",".join(diff) or None


# --- BCB e Yahoo ----------------------------------------------------------------------------


def ingest_selic(session: Session, *, content: bytes, raw_file_id: int) -> IngestResult:
    points = parse_sgs(content)
    if not points:
        return IngestResult(rows=0, empty=True)
    stmt = insert(RiskFreeRate).values(
        [
            {"day": p.day, "rate": p.rate, "series_code": SELIC_SERIES, "raw_file_id": raw_file_id}
            for p in points
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["day"], set_={"rate": stmt.excluded.rate, "raw_file_id": stmt.excluded.raw_file_id}
    )
    session.execute(stmt)
    return IngestResult(rows=len(points))


def ingest_dividends(session: Session, *, content: bytes, raw_file_id: int, ticker: str) -> IngestResult:
    """Histórico do Yahoo: tipo desconhecido e não confirmado (RS-02)."""
    points = parse_dividends(content, expected_symbol=ticker)
    if not points:
        return IngestResult(rows=0, empty=True)
    stmt = insert(CorporateAction).values(
        [
            {
                "ticker": ticker,
                "ex_date": p.ex_date,
                "amount": p.amount,
                "kind": "unknown",
                "source": "yahoo",
                "confirmed": False,
                "raw_file_id": raw_file_id,
            }
            for p in points
        ]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_corporate_actions_ticker_day_source",
        set_={
            "amount": stmt.excluded.amount,
            "raw_file_id": stmt.excluded.raw_file_id,
            "updated_at": func.now(),
        },
    )
    session.execute(stmt)
    return IngestResult(rows=len(points))
