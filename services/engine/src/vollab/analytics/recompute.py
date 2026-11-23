"""Recálculos de volatilidade no worker, depois da coleta (PRD §5.5, PRD-NF-06, ADR-08).

Job `vol_recompute`, enfileirado ao fim de cada coleta e quando um provento manual muda. Para cada
ativo ativo:

1. barras de 5 min e resumo do pregão (RN-VOL-08) dos pregões novos ou sem resumo;
2. RV por estimador e janela, sempre a série inteira (barato: só agregados diários);
3. IV por negócio, sincronizada (RN-VOL-03), e IV de referência diária (RN-VOL-06);
4. IV ATM por vencimento e de prazo constante (RF-VOL-03/05, RN-VOL-05).

Idempotente: cada passo apaga e regrava o que calcula. Commit por pregão; se o worker parar, o
job volta para a fila e refaz só o que faltou (os pregões sem resultado entram no escopo).
"""

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Any, cast

import numpy as np
import psycopg
import structlog
from numpy.typing import NDArray
from sqlalchemy import delete, insert, select, text
from sqlalchemy.orm import Session

from vollab.analytics.market import (
    OPTION_TRADES_SQL,
    DividendInfo,
    RateCurve,
    UnderlyingTrades,
    active_tickers,
    load_daily_series,
    load_dividends,
    load_holidays,
    load_rates,
    load_underlying_trades,
    underlying_isin,
)
from vollab.analytics.params import VolParams, vol_params_from_config
from vollab.collection.params import CollectionParams, ensure_config_version, params_from_config
from vollab.collection.planner import PHASE_OPTIONS, PHASE_UNDERLYING
from vollab.db.models import (
    FIXED_USER_ID,
    AtmTermPoint,
    CollectionItem,
    ConstantMaturityVol,
    DailyBar,
    IntradayBar,
    IntradaySession,
    Job,
    JobStatus,
    OptionDailyQuote,
    OptionSeries,
    RealizedVol,
)
from vollab.jobs import queue
from vollab.jobs.control import JobInterruptedError, stop_requested
from vollab.jobs.handlers import register
from vollab.quant.calendar import count_business_days
from vollab.quant.implied import (
    SmilePoint,
    TermPoint,
    atm_iv,
    constant_maturity,
    reference_iv,
    synchronize,
)
from vollab.quant.intraday import IntradayError, build_session, session_close_from_closing_trade
from vollab.quant.pricing import (
    BUSINESS_DAYS_PER_YEAR,
    IvStatus,
    bs_price,
    continuous_rate,
    implied_vol,
)
from vollab.quant.vol import Estimator, daily_terms, rolling

log = structlog.get_logger("vollab.analytics")

JOB_KIND = "vol_recompute"
_BATCH = 2000


def enqueue_recompute(
    session: Session,
    *,
    user_id: uuid.UUID,
    days: list[date] | None = None,
    tickers: list[str] | None = None,
    full: bool = False,
    skip_intraday: bool = False,
    reason: str,
) -> None:
    """Enfileira o recálculo. `skip_intraday`: barras de 5 min não dependem de proventos, então a
    edição de um provento só refaz RV e IV (revisão de performance da Etapa 3)."""
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "days": sorted({d.isoformat() for d in days or []}),
        "full": full,
        "skip_intraday": skip_intraday,
        "reason": reason,
    }
    if tickers:
        payload["tickers"] = sorted(set(tickers))
        # Mesmo pedido já na fila (edições seguidas de provento): não duplica.
        queued = session.scalars(
            select(Job).where(Job.kind == JOB_KIND, Job.status == JobStatus.QUEUED)
        ).all()
        for job in queued:
            same = {k: v for k, v in job.payload.items() if k != "reason"}
            if same == {k: v for k, v in payload.items() if k != "reason"}:
                return
    queue.enqueue(session, user_id=user_id, kind=JOB_KIND, payload=payload, max_attempts=3)


@register(JOB_KIND)
def run_recompute_job(session: Session, payload: dict[str, Any]) -> None:
    user_id = uuid.UUID(str(payload.get("user_id") or FIXED_USER_ID))
    days = {date.fromisoformat(d) for d in payload.get("days") or []}
    tickers = payload.get("tickers")
    version = ensure_config_version(session, user_id=user_id)
    session.commit()
    recomputer = Recomputer(
        session,
        version_id=version.id,
        vol=vol_params_from_config(version),
        collection=params_from_config(version),
    )
    recomputer.run(
        tickers=list(tickers) if isinstance(tickers, list) else None,
        days=days,
        full=bool(payload.get("full")),
        skip_intraday=bool(payload.get("skip_intraday")),
    )


@dataclass(frozen=True, slots=True)
class _SeriesDay:
    series_id: int
    code: str
    expiry: date
    is_call: bool
    is_weekly: bool
    strike: float
    trades_count: int


@dataclass(frozen=True, slots=True)
class _PerTrade:
    sidx: NDArray[np.int64]
    synced: NDArray[np.bool_]
    und_price: NDArray[np.float64]
    lag_s: NDArray[np.float64]
    iv: NDArray[np.float64]
    status: NDArray[np.int8]


@dataclass(frozen=True, slots=True)
class _PerSeries:
    series: list[_SeriesDay]
    k_eff: NDArray[np.float64]
    du: NDArray[np.int64]
    pvd: NDArray[np.float64]


class Recomputer:
    def __init__(
        self,
        session: Session,
        *,
        version_id: int,
        vol: VolParams,
        collection: CollectionParams,
        stop: Any = stop_requested,
    ) -> None:
        self.session = session
        self.version_id = version_id
        self.vol = vol
        self.collection = collection
        self.stop = stop
        self.holidays = load_holidays(session)
        self.rates: RateCurve = load_rates(session)

    # Orquestração ---------------------------------------------------------------------------

    def run(
        self, *, tickers: list[str] | None, days: set[date], full: bool, skip_intraday: bool = False
    ) -> None:
        for ticker in tickers or active_tickers(self.session):
            bound = log.bind(ticker=ticker)
            dividends = load_dividends(self.session, ticker)
            intraday_days = [] if skip_intraday else self._scope(ticker, days, full, phase=PHASE_UNDERLYING)
            iv_days = self._scope(ticker, days, full, phase=PHASE_OPTIONS)
            # Um laço por pregão: os negócios do ativo são lidos uma vez e servem às duas fases.
            for d in sorted(set(intraday_days) | set(iv_days)):
                self._check_stop()
                trades = load_underlying_trades(self.session, ticker, d)
                if d in intraday_days:
                    self.intraday_day(ticker, d, trades)
                if d in iv_days:
                    self.implied_day(ticker, d, dividends, trades)
                    self.term_structure_day(ticker, d, dividends)
                self.session.commit()
            self.realized(ticker, dividends)
            self.session.commit()
            bound.info("vol.recomputed", intraday_days=len(intraday_days), iv_days=len(iv_days))

    def _check_stop(self) -> None:
        if self.stop():
            raise JobInterruptedError("Worker encerrado; o recálculo continua quando ele voltar.")

    def _scope(self, ticker: str, days: set[date], full: bool, *, phase: int) -> list[date]:
        """Pregões com negócios coletados: os pedidos e os que ainda não têm resultado."""
        candidates = set(
            self.session.scalars(
                select(CollectionItem.trade_date)
                .where(
                    CollectionItem.source == "b3_trades",
                    CollectionItem.underlying == ticker,
                    CollectionItem.phase == phase,
                    CollectionItem.status == "ok",
                )
                .distinct()
            )
        )
        if full:
            return sorted(candidates)
        if phase == PHASE_UNDERLYING:
            done = set(
                self.session.scalars(
                    select(IntradaySession.trade_date).where(IntradaySession.ticker == ticker)
                )
            )
        else:
            # O prazo constante é sempre gravado (mesmo indisponível): marca o pregão como feito.
            done = set(
                self.session.scalars(
                    select(ConstantMaturityVol.as_of).where(ConstantMaturityVol.ticker == ticker).distinct()
                )
            )
        return sorted((candidates & days) | (candidates - done))

    # 1. Intradiário -------------------------------------------------------------------------

    def intraday_day(self, ticker: str, day: date, trades: UnderlyingTrades) -> None:
        s = self.session
        s.execute(delete(IntradayBar).where(IntradayBar.ticker == ticker, IntradayBar.trade_date == day))
        s.execute(
            delete(IntradaySession).where(IntradaySession.ticker == ticker, IntradaySession.trade_date == day)
        )
        bar = s.get(DailyBar, (ticker, day))
        if bar is None:
            return
        t, ids, p, q = trades
        if t.size == 0:
            return
        params = self.vol.intraday
        open_s = params.session_open.hour * 3600 + params.session_open.minute * 60
        try:
            sess = build_session(
                t,
                ids,
                p,
                q,
                official_open=float(bar.open),
                official_close=float(bar.close),
                session_open_s=open_s,
                bar_minutes=params.bar_minutes,
                min_coverage=params.min_coverage,
            )
        except IntradayError:
            log.warning("vol.intraday_skipped", ticker=ticker, day=str(day))
            return
        s.add(
            IntradaySession(
                ticker=ticker,
                trade_date=day,
                session_open=_time(sess.session_open_s),
                session_close=_time(sess.session_close_s),
                bar_minutes=sess.bar_minutes,
                bars_total=sess.bars_total,
                bars_with_trades=sess.bars_with_trades,
                coverage=sess.coverage,
                complete=sess.complete,
                intraday_variance=sess.intraday_variance,
                trades_used=sess.trades_used,
            )
        )
        s.execute(
            insert(IntradayBar),
            [
                {
                    "ticker": ticker,
                    "trade_date": day,
                    "bar_start": _time(int(start)),
                    "price": round(float(price), 6),
                    "trades_count": int(n),
                    "quantity": int(qty),
                }
                for start, price, n, qty in zip(
                    sess.bar_start_s, sess.bar_price, sess.bar_trades, sess.bar_quantity, strict=True
                )
            ],
        )

    # 2. RV ----------------------------------------------------------------------------------

    def realized(self, ticker: str, dividends: dict[date, DividendInfo]) -> None:
        s = self.session
        s.execute(delete(RealizedVol).where(RealizedVol.ticker == ticker))
        series = load_daily_series(s, ticker, self.holidays, dividends)
        if series is None:
            return
        terms = daily_terms(series.open, series.high, series.low, series.close, series.prev_close_adj)
        n = len(series.days)
        intraday_var = np.full(n, np.nan)
        incomplete = np.zeros(n, dtype=bool)
        first_intraday: int | None = None
        sessions = s.execute(
            select(
                IntradaySession.trade_date, IntradaySession.intraday_variance, IntradaySession.complete
            ).where(IntradaySession.ticker == ticker)
        )
        for day, variance, complete in sessions:
            i = series.index(day)
            if i is None:
                continue
            first_intraday = i if first_intraday is None else min(first_intraday, i)
            if complete:
                intraday_var[i] = variance
            else:
                incomplete[i] = True
        rows: list[dict[str, Any]] = []
        for window in self.vol.windows_bd:
            for est in Estimator:
                if est is Estimator.INTRADAY_5M and first_intraday is None:
                    continue
                res = rolling(est, terms, window, intraday_var=intraday_var)
                start = (
                    window if est is not Estimator.INTRADAY_5M else max(window - 1, cast(int, first_intraday))
                )
                for i in range(start, n):
                    vol = float(res.vol[i])
                    ok = math.isfinite(vol)
                    reason: str | None = None
                    if not ok:
                        if res.missing[i] == 0:
                            reason = "non_positive"
                        elif est is Estimator.INTRADAY_5M and incomplete[i - window + 1 : i + 1].any():
                            reason = "incomplete_sessions"
                        else:
                            reason = "missing_days"
                    rows.append(
                        {
                            "ticker": ticker,
                            "as_of": series.days[i],
                            "estimator": est.value,
                            "window_bd": window,
                            "variance_annual": float(res.variance_annual[i]) if ok else None,
                            "vol": vol if ok else None,
                            "missing_days": int(res.missing[i]),
                            "status": "ok" if ok else "insufficient_data",
                            "reason": reason,
                            "config_version_id": self.version_id,
                        }
                    )
        for start in range(0, len(rows), _BATCH):
            s.execute(insert(RealizedVol), rows[start : start + _BATCH])

    # 3. IV ----------------------------------------------------------------------------------

    def _series_of_day(self, isin: str, day: date) -> list[_SeriesDay]:
        rows = self.session.execute(
            text(
                """
                SELECT s.id, s.code, s.expiry, s.option_type = 'call', s.is_weekly,
                       st.strike::float8, st.trades_count
                FROM option_series s
                JOIN option_daily_stats st ON st.series_id = s.id AND st.trade_date = :d
                WHERE s.underlying_isin = :isin AND s.expiry > :d
                """
            ),
            {"isin": isin, "d": day},
        )
        return [_SeriesDay(*r) for r in rows]

    def _dividends_until(
        self, day: date, expiry: date, dividends: dict[date, DividendInfo], rate_c: float
    ) -> tuple[float, float]:
        """(VP dos proventos com data ex em (day, expiry], soma nominal deles)."""
        pv = total = 0.0
        for ex, info in dividends.items():
            if day < ex <= expiry:
                t_ex = count_business_days(day, ex, self.holidays) / BUSINESS_DAYS_PER_YEAR
                pv += info.amount * math.exp(-rate_c * t_ex)
                total += info.amount
        return pv, total

    def implied_day(
        self, ticker: str, day: date, dividends: dict[date, DividendInfo], trades: UnderlyingTrades
    ) -> None:
        s = self.session
        isin = underlying_isin(s, ticker)
        if isin is None:
            return
        series = self._series_of_day(isin, day)
        ids = [x.series_id for x in series]
        if ids:
            s.execute(
                text("DELETE FROM implied_vols WHERE trade_date = :d AND series_id = ANY(:ids)"),
                {"d": day, "ids": ids},
            )
            s.execute(
                delete(OptionDailyQuote).where(
                    OptionDailyQuote.trade_date == day, OptionDailyQuote.series_id.in_(ids)
                )
            )
        bar = s.get(DailyBar, (ticker, day))
        rate = self.rates.on(day)
        if not series or bar is None or rate is None:
            if series and rate is None:
                log.warning("vol.iv_skipped_no_rate", ticker=ticker, day=str(day))
            return
        und_t, und_ids, und_p, _ = trades
        if und_t.size == 0:
            return
        by_code = {x.code: i for i, x in enumerate(series)}
        opt_rows = s.execute(
            text(OPTION_TRADES_SQL),
            {"codes": list(by_code), "d": day},
        ).all()
        if not opt_rows:
            return
        rate_c = continuous_rate(rate)
        params = self.vol.implied
        n = len(opt_rows)
        opt_t = np.fromiter((r[0] for r in opt_rows), dtype=np.float64, count=n)
        opt_price = np.fromiter((r[2] for r in opt_rows), dtype=np.float64, count=n)
        sidx = np.fromiter((by_code[r[4]] for r in opt_rows), dtype=np.int64, count=n)

        # Prazo, proventos e strike efetivo por série (RN-PRC-01/05, RN-DAD-03).
        k = len(series)
        du = np.array([count_business_days(day, x.expiry, self.holidays) for x in series], dtype=np.int64)
        pvd = np.zeros(k)
        k_eff = np.array([x.strike for x in series])
        for i, x in enumerate(series):
            pv, total = self._dividends_until(day, x.expiry, dividends, rate_c)
            pvd[i] = pv
            if params.dividend_protected_strikes:
                k_eff[i] = x.strike - total
        is_call = np.array([x.is_call for x in series])

        sync = synchronize(opt_t, und_t, max_lag_s=params.sync_window_s)
        synced = sync.synced
        und_price = np.where(sync.underlying_index >= 0, und_p[np.maximum(sync.underlying_index, 0)], np.nan)
        iv = np.full(n, np.nan)
        status = np.full(n, IvStatus.INVALID_INPUT, dtype=np.int8)
        if synced.any():
            sel = np.flatnonzero(synced)
            si = sidx[sel]
            res = implied_vol(
                opt_price[sel],
                und_price[sel],
                k_eff[si],
                du[si] / BUSINESS_DAYS_PER_YEAR,
                rate_c,
                is_call[si],
                pvd[si],
            )
            iv[sel] = res.iv
            status[sel] = res.status

        self._copy_implied(
            day,
            opt_rows,
            _PerTrade(sidx, synced, und_price, sync.lag_s, iv, status),
            _PerSeries(series, k_eff, du, pvd),
            rate_c,
        )

        # IV de referência por série (RN-VOL-06).
        closing_s = float(und_t[int(np.argmax(und_ids))])
        window_start = session_close_from_closing_trade(closing_s) - params.reference_window_min * 60
        liquidity = self.collection.liquidity
        close = float(bar.close)
        quotes: list[dict[str, Any]] = []
        for i, x in enumerate(series):
            mine = sidx == i
            total_trades = int(mine.sum())
            if total_trades == 0:
                continue
            mine_synced = mine & synced
            ref = reference_iv(
                opt_t[mine_synced],
                iv[mine_synced],
                window_start_s=window_start,
                min_trades=params.reference_min_trades,
            )
            implied_price = None
            if ref.iv is not None and du[i] > 0:
                implied_price = round(
                    float(
                        bs_price(
                            close, k_eff[i], du[i] / BUSINESS_DAYS_PER_YEAR, rate_c, ref.iv, x.is_call, pvd[i]
                        )
                    ),
                    6,
                )
            quotes.append(
                {
                    "series_id": x.series_id,
                    "trade_date": day,
                    "iv": ref.iv,
                    "status": ref.status,
                    "trades_valid": total_trades,
                    "trades_synced": int(mine_synced.sum()),
                    "trades_lag_discarded": total_trades - int(mine_synced.sum()),
                    "trades_no_solution": int((mine_synced & (status != IvStatus.OK)).sum()),
                    "trades_used": ref.trades_used,
                    "implied_price": implied_price,
                    "underlying_close": close,
                    "strike": x.strike,
                    "effective_strike": round(float(k_eff[i]), 6),
                    "days_to_expiry_bd": int(du[i]),
                    "liquid": x.trades_count >= liquidity.min_trades
                    and (liquidity.include_weeklies or not x.is_weekly),
                    "config_version_id": self.version_id,
                }
            )
        if quotes:
            s.execute(insert(OptionDailyQuote), quotes)

    def _copy_implied(
        self, day: date, rows: Sequence[Any], trade: "_PerTrade", per: "_PerSeries", rate_c: float
    ) -> None:
        """IV por negócio sincronizado (os descartados pela defasagem só são contados)."""
        cols = (
            "series_id, trade_date, trade_id, traded_at, option_price, underlying_price, lag_ms, strike, "
            "days_to_expiry_bd, rate_continuous, pv_dividends, iv, iv_status"
        )
        dbapi = cast(psycopg.Connection[Any], self.session.connection().connection.driver_connection)
        with dbapi.cursor() as cur, cur.copy(f"COPY implied_vols ({cols}) FROM STDIN") as copy:
            for j in np.flatnonzero(trade.synced):
                r = rows[int(j)]
                i = int(trade.sidx[j])
                v = float(trade.iv[j])
                copy.write_row(
                    (
                        per.series[i].series_id,
                        day,
                        r[1],
                        r[5],
                        round(float(r[2]), 6),
                        round(float(trade.und_price[j]), 6),
                        round(float(trade.lag_s[j]) * 1000),
                        round(float(per.k_eff[i]), 6),
                        int(per.du[i]),
                        rate_c,
                        float(per.pvd[i]),
                        v if math.isfinite(v) else None,
                        int(trade.status[j]),
                    )
                )

    # 4. Estrutura a termo e prazo constante ---------------------------------------------------

    def term_structure_day(self, ticker: str, day: date, dividends: dict[date, DividendInfo]) -> None:
        s = self.session
        s.execute(delete(AtmTermPoint).where(AtmTermPoint.ticker == ticker, AtmTermPoint.as_of == day))
        s.execute(
            delete(ConstantMaturityVol).where(
                ConstantMaturityVol.ticker == ticker, ConstantMaturityVol.as_of == day
            )
        )
        isin = underlying_isin(s, ticker)
        bar = s.get(DailyBar, (ticker, day))
        rate = self.rates.on(day)
        if isin is None or bar is None or rate is None:
            # Grava o prazo constante indisponível: o pregão conta como feito e não volta a cada job.
            missing = "sem OHLC oficial" if bar is None else "sem Selic" if rate is None else "sem ISIN"
            s.add(
                ConstantMaturityVol(
                    ticker=ticker,
                    as_of=day,
                    target_bd=self.vol.constant_maturity_bd,
                    iv=None,
                    status="unavailable",
                    reason=f"{missing} no pregão",
                    config_version_id=self.version_id,
                )
            )
            return
        rate_c = continuous_rate(rate)
        rows = s.execute(
            select(
                OptionSeries.expiry,
                OptionSeries.option_type,
                OptionSeries.is_weekly,
                OptionDailyQuote.effective_strike,
                OptionDailyQuote.iv,
                OptionDailyQuote.days_to_expiry_bd,
            )
            .join(OptionSeries, OptionSeries.id == OptionDailyQuote.series_id)
            .where(
                OptionSeries.underlying_isin == isin,
                OptionDailyQuote.trade_date == day,
                OptionDailyQuote.liquid.is_(True),
                OptionDailyQuote.iv.is_not(None),
            )
        ).all()
        by_expiry: dict[date, list[Any]] = defaultdict(list)
        for r in rows:
            by_expiry[r[0]].append(r)
        liquidity = self.collection.liquidity
        spot = float(bar.close)
        term: list[tuple[date, int, TermPoint]] = []
        atm_rows: list[dict[str, Any]] = []
        for expiry, pts in sorted(by_expiry.items()):
            du = int(pts[0][5])
            if du <= 0:
                continue
            t = du / BUSINESS_DAYS_PER_YEAR
            pv, _ = self._dividends_until(day, expiry, dividends, rate_c)
            forward = (spot - pv) * math.exp(rate_c * t)
            res = atm_iv(
                [SmilePoint(float(p[3]), float(p[4]), p[1] == "call") for p in pts],
                forward,
                k_min=float(liquidity.moneyness_min),
                k_max=float(liquidity.moneyness_max),
            )
            atm_rows.append(
                {
                    "ticker": ticker,
                    "as_of": day,
                    "expiry": expiry,
                    "days_to_expiry_bd": du,
                    "forward": forward,
                    "atm_iv": res.iv,
                    "status": "ok" if res.iv is not None else "unavailable",
                    "reason": res.reason,
                    "lower_strike": res.lower_strike,
                    "upper_strike": res.upper_strike,
                    "is_weekly": bool(pts[0][2]),
                    "config_version_id": self.version_id,
                }
            )
            if res.iv is not None:
                term.append((expiry, du, TermPoint(t, res.iv)))
        if atm_rows:
            s.execute(insert(AtmTermPoint), atm_rows)
        target = self.vol.constant_maturity_bd
        cm = constant_maturity([p for _, _, p in term], target / BUSINESS_DAYS_PER_YEAR)
        row: dict[str, Any] = {
            "ticker": ticker,
            "as_of": day,
            "target_bd": target,
            "iv": cm.iv,
            "status": "ok" if cm.iv is not None else "unavailable",
            "reason": cm.reason,
            "config_version_id": self.version_id,
        }
        if cm.iv is not None:
            lower = [e for e, du, p in term if p.t == cm.t1]
            upper = [e for e, du, p in term if p.t == cm.t2]
            row["lower_expiry"] = lower[0] if lower else None
            row["upper_expiry"] = upper[0] if upper else None
        elif term:
            # RN-VOL-05: a ATM do vencimento disponível mais próximo do prazo, com o prazo efetivo.
            expiry, du, p = min(term, key=lambda x: abs(x[1] - target))
            row |= {"fallback_expiry": expiry, "fallback_bd": du, "fallback_iv": p.iv}
        s.execute(insert(ConstantMaturityVol), [row])


def _time(seconds: int) -> time:
    return time(seconds // 3600, (seconds % 3600) // 60, seconds % 60)
