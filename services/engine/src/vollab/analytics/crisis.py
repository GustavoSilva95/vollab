"""Cenário de crise histórica (PRD 1.10 §5.9; BRD 1.7 QA-12, RF-RSK-03).

Job `crisis_measure` (worker, sob demanda): para cada ativo e episódio, lê o COTAHIST anual do ano do
episódio (baixado uma vez; anos passados são reaproveitados do cache bruto), mede o choque de preço
(pior retorno em `crisis_horizon_bd` pregões, ajustado por proventos) e o choque de vol (IV ATM dos
fechamentos das opções, aproximada; fallback na RV de 20 pregões) e grava em `crisis_measurements`.
Nada entra em `daily_bars`: o histórico diário do sistema continua com 1 ano.

Arquivos da B3, do BCB e do Yahoo são entrada não confiável (PRD-NF-05): os adaptadores limitam
tamanho e formato; aqui só se usam os registros já validados pelo parser.
"""

import math
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from vollab.analytics.market import RateCurve, load_holidays
from vollab.analytics.params import (
    CrisisEpisode,
    RiskParams,
    cost_params_from_config,
    risk_params_from_config,
)
from vollab.collection.params import ensure_config_version
from vollab.collection.planner import today_sao_paulo
from vollab.data.b3_cotahist import CotahistRecord, RecordFilter, read_cotahist
from vollab.data.bcb import SgsParseError, parse_sgs
from vollab.data.http import SourceNotFoundError, SourceResponseError, TransientSourceError
from vollab.data.raw_cache import RawCache
from vollab.data.sources import MarketDataSources, build_sources
from vollab.data.yahoo import YahooParseError, parse_dividends
from vollab.db.models import FIXED_USER_ID, CrisisMeasurement, Job, JobStatus, RawFile, Underlying
from vollab.jobs import queue
from vollab.jobs.handlers import register
from vollab.quant.calendar import business_days, count_business_days
from vollab.quant.crisis import (
    CrisisShock,
    OptionClose,
    atm_iv,
    rv_zero_mean,
    worst_day,
    worst_window,
)
from vollab.quant.pricing import continuous_rate
from vollab.quant.risk import Scenario, Shock
from vollab.settings import get_settings

log = structlog.get_logger("vollab.crisis")
JOB_KIND = "crisis_measure"
SOURCE = "b3_cotahist_annual"
OPTIONS_MARGIN = timedelta(days=10)  # opções lidas um pouco antes do episódio (pregão anterior à janela)
MIN_DAYS_BD = 10


def enqueue_crisis(
    session: Session, *, user_id: uuid.UUID, tickers: list[str] | None, reason: str
) -> Job | None:
    """Enfileira a medição; não duplica um pedido igual ou mais amplo ainda na fila."""
    payload: dict[str, Any] = {"user_id": str(user_id), "reason": reason}
    if tickers:
        payload["tickers"] = sorted(set(tickers))
    queued = session.scalars(
        select(Job).where(
            Job.kind == JOB_KIND,
            Job.user_id == user_id,
            Job.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
    ).all()
    for job in queued:
        ts = job.payload.get("tickers")
        if ts is None or (tickers and set(tickers) <= set(ts)):
            return None
    return queue.enqueue(session, user_id=user_id, kind=JOB_KIND, payload=payload, max_attempts=3)


@register(JOB_KIND)
def run_crisis_job(session: Session, payload: dict[str, Any]) -> None:
    user_id = uuid.UUID(str(payload.get("user_id") or FIXED_USER_ID))
    tickers = payload.get("tickers")
    settings = get_settings()
    sources = build_sources(settings)
    try:
        CrisisMeasurer(session, user_id=user_id, sources=sources, cache=RawCache(settings.raw_data_dir)).run(
            list(tickers) if isinstance(tickers, list) else None
        )
    finally:
        sources.close()


class _EpisodeFilter(RecordFilter):
    """À vista o ano inteiro (RV e retornos); opções só perto dos episódios (memória)."""

    def __init__(self, *, tickers: Iterable[str], isins: Iterable[str], windows: list[tuple[date, date]]):
        super().__init__(underlying_tickers=tickers, underlying_isins=isins, options=True)
        self.windows = [(f"{a:%Y%m%d}", f"{b:%Y%m%d}") for a, b in windows]

    def prefilter(self, line: str) -> bool:
        if not super().prefilter(line):
            return False
        if line[24:27] == "010":
            return True
        day = line[2:10]
        return any(a <= day <= b for a, b in self.windows)


@dataclass(frozen=True, slots=True)
class _Year:
    underlying: dict[str, list[CotahistRecord]]  # por ticker, em ordem de data
    options: dict[str, dict[date, list[CotahistRecord]]]  # por ISIN e pregão


class CrisisMeasurer:
    def __init__(
        self, session: Session, *, user_id: uuid.UUID, sources: MarketDataSources, cache: RawCache
    ) -> None:
        self.session = session
        self.user_id = user_id
        self.sources = sources
        self.cache = cache
        version = ensure_config_version(session, user_id=user_id)
        session.commit()
        self.version_id = version.id
        self.risk: RiskParams = risk_params_from_config(version)
        # Mesmo mínimo de negócios da liquidez do edge (QA-06: 20).
        self.min_trades = cost_params_from_config(version).spread_min_trades
        self.holidays = load_holidays(session)
        self.today = today_sao_paulo(get_settings())
        self.engine_version = get_settings().engine_version

    def run(self, tickers: list[str] | None) -> None:
        rows = self.session.execute(
            select(Underlying.ticker, Underlying.isin).where(Underlying.user_id == self.user_id)
        ).all()
        universe = {t: i for t, i in rows if i and (tickers is None or t in tickers)}
        if not universe:
            return
        by_year: dict[int, list[CrisisEpisode]] = {}
        for ep in self.risk.crisis_episodes:
            for y in range(ep.start.year, ep.end.year + 1):
                by_year.setdefault(y, []).append(ep)
        # Um episódio por vez: só os anuais dele ficam em memória (revisão de segurança, I-1).
        for ep in self.risk.crisis_episodes:
            span = range(ep.start.year, ep.end.year + 1)
            years: dict[int, _Year] = {}
            missing = None
            for y in span:
                loaded = self._year(y, universe, [ep])
                if loaded is None:
                    missing = y
                    break
                years[y] = loaded
            rates = self._rates(ep) if missing is None else None
            for ticker, isin in sorted(universe.items()):
                if missing is not None:
                    shock = _with(_EMPTY, reason=f"COTAHIST anual de {missing} indisponível na fonte")
                    self._save(ticker, ep, shock, False)
                    continue
                divs, checked = self._dividends(ticker, ep)
                shock = self.measure(ticker, isin, ep, years, rates, divs)
                self._save(ticker, ep, shock, checked)
            self.session.commit()
            del years

    # Fontes --------------------------------------------------------------------------------

    def _annual(self, year: int) -> bytes:
        if year < self.today.year:
            cached = self.session.scalar(
                select(RawFile)
                .where(RawFile.source == SOURCE, RawFile.query_key == str(year), RawFile.http_status == 200)
                .order_by(RawFile.id.desc())
                .limit(1)
            )
            if cached is not None:
                try:
                    return self.cache.read(cached.relative_path, expected_sha256=cached.sha256)
                except FileNotFoundError:
                    pass  # cache bruto apagado: baixa de novo
        fetched = self.sources.cotahist_annual(year)
        stored = self.cache.store(SOURCE, fetched.content, "zip")
        self.session.add(
            RawFile(
                source=SOURCE,
                query_key=str(year),
                query_date=date(year, 12, 31),
                relative_path=stored.relative_path,
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                http_status=fetched.http_status,
                content_format=fetched.content_format,
            )
        )
        self.session.commit()
        return fetched.content

    def _year(self, year: int, universe: dict[str, str], eps: list[CrisisEpisode]) -> _Year | None:
        try:
            content = self._annual(year)
        except SourceNotFoundError:
            return None
        windows = [(ep.start - OPTIONS_MARGIN, ep.end) for ep in eps]
        keep = _EpisodeFilter(tickers=universe, isins=universe.values(), windows=windows)
        parsed = read_cotahist(content, keep=keep, annual=True)
        underlying: dict[str, list[CotahistRecord]] = {}
        options: dict[str, dict[date, list[CotahistRecord]]] = {}
        for r in parsed.records:
            if r.is_option:
                if r.expiry is not None and not r.is_weekly:
                    options.setdefault(r.isin, {}).setdefault(r.trade_date, []).append(r)
            elif r.ticker in universe:
                underlying.setdefault(r.ticker, []).append(r)
        for recs in underlying.values():
            recs.sort(key=lambda r: r.trade_date)
        return _Year(underlying, options)

    def _rates(self, ep: CrisisEpisode) -> RateCurve | None:
        try:
            fetched = self.sources.selic(ep.start - timedelta(days=45), ep.end)
            points = parse_sgs(fetched.content)
        except (SourceNotFoundError, SourceResponseError, TransientSourceError, SgsParseError):
            return None
        return RateCurve((p.day, float(p.rate)) for p in points) if points else None

    def _dividends(self, ticker: str, ep: CrisisEpisode) -> tuple[dict[date, float], bool]:
        try:
            fetched = self.sources.dividends_range(ticker, date(ep.start.year, 1, 1), ep.end)
            points = parse_dividends(fetched.content, expected_symbol=ticker)
        except (SourceNotFoundError, SourceResponseError, TransientSourceError, YahooParseError):
            return {}, False
        return {p.ex_date: float(p.amount) for p in points}, True

    # Medição ----------------------------------------------------------------------------------

    def measure(
        self,
        ticker: str,
        isin: str,
        ep: CrisisEpisode,
        years: dict[int, _Year],
        rates: RateCurve | None,
        dividends: dict[date, float],
    ) -> CrisisShock:
        none = CrisisShock("unavailable", None, None, None, None, None, None, None, None, None, None)
        recs = [r for y in range(ep.start.year, ep.end.year + 1) for r in years[y].underlying.get(ticker, [])]
        bars = {r.trade_date: float(r.last) / max(r.quote_factor, 1) for r in recs}
        if not bars:
            return _with(none, reason="ativo sem negociação no ano do episódio")
        first = min(bars)
        days = [d for d in business_days(first, max(bars), self.holidays) if d in bars]
        closes = [bars[d] for d in days]
        rets = [float("nan")]
        for i in range(1, len(days)):
            prev = closes[i - 1] - dividends.get(days[i], 0.0)
            rets.append(math.log(closes[i] / prev) if prev > 0 and closes[i] > 0 else float("nan"))
        idx = [i for i, d in enumerate(days) if ep.start <= d <= ep.end]
        if len(idx) < self.risk.crisis_horizon_bd:
            return _with(none, reason="ativo sem negociação suficiente no episódio")
        win = worst_window(rets, idx[0], idx[-1], self.risk.crisis_horizon_bd)
        if win is None:
            return _with(none, reason="sem janela completa de retornos no episódio")
        wd = worst_day(rets, idx[0], idx[-1])
        before_i = win.start - 1
        if before_i < 0:
            return _with(none, reason="sem o pregão anterior à janela")
        d0, d1 = days[before_i], days[win.end]
        vol_method = "atm_iv"
        reason = None
        v0 = v1 = None
        if rates is not None:
            v0 = self._atm(isin, d0, bars[d0], years, rates)
            v1 = self._atm(isin, d1, bars[d1], years, rates)
        if v0 is None or v1 is None:
            vol_method = "rv20"
            reason = (
                "IV ATM indisponível (sem Selic do episódio)"
                if rates is None
                else "IV ATM indisponível (opções ATM sem negócios suficientes)"
            ) + "; choque de vol pela RV de 20 pregões"
            v0 = rv_zero_mean(rets, before_i)
            v1 = rv_zero_mean(rets, win.end)
        if v0 is None or v1 is None:
            return _with(none, reason="sem IV ATM nem RV de 20 pregões em volta da janela")
        return CrisisShock(
            status="ok",
            reason=reason,
            window_start=days[win.start],
            window_end=d1,
            price_shock=win.simple_return,
            worst_day=days[wd[0]] if wd else None,
            worst_day_return=math.expm1(wd[1]) if wd else None,
            vol_shock=v1 - v0,
            vol_method=vol_method,
            vol_before=v0,
            vol_after=v1,
        )

    def _atm(
        self, isin: str, day: date, spot: float, years: dict[int, _Year], rates: RateCurve
    ) -> float | None:
        rate = rates.on(day)
        if rate is None:
            return None
        opts = []
        for r in years[day.year].options.get(isin, {}).get(day, []):
            if r.expiry is None:  # pragma: no cover (filtrado em _year)
                continue
            h = count_business_days(day, r.expiry, self.holidays)
            factor = max(r.quote_factor, 1)
            if h <= 0 or r.last <= 0:
                continue
            opts.append(
                OptionClose(
                    r.option_type == "call", float(r.strike), h, float(r.last) / factor, r.trades_count
                )
            )
        return atm_iv(spot, opts, continuous_rate(rate), min_days_bd=MIN_DAYS_BD, min_trades=self.min_trades)

    def _save(self, ticker: str, ep: CrisisEpisode, s: CrisisShock, checked: bool) -> None:
        self.session.execute(
            delete(CrisisMeasurement).where(
                CrisisMeasurement.user_id == self.user_id,
                CrisisMeasurement.ticker == ticker,
                CrisisMeasurement.episode == ep.key,
            )
        )
        self.session.add(
            CrisisMeasurement(
                user_id=self.user_id,
                ticker=ticker,
                episode=ep.key,
                status=s.status,
                reason=s.reason,
                window_start=s.window_start,
                window_end=s.window_end,
                price_shock=s.price_shock,
                worst_day=s.worst_day,
                worst_day_return=s.worst_day_return,
                vol_shock=s.vol_shock,
                vol_method=s.vol_method,
                vol_before=s.vol_before,
                vol_after=s.vol_after,
                dividends_checked=checked,
                config_version_id=self.version_id,
                engine_version=self.engine_version,
            )
        )


_EMPTY = CrisisShock("unavailable", None, None, None, None, None, None, None, None, None, None)


def _with(shock: CrisisShock, *, reason: str) -> CrisisShock:
    return CrisisShock("unavailable", reason, *([None] * 9))


# --- Leitura: choques vigentes (medidos ou manuais) --------------------------------------------


@dataclass(frozen=True, slots=True)
class CrisisValue:
    ticker: str
    episode: str
    label: str
    status: str  # ok | unavailable
    origin: str  # approximate | manual
    price_shock: float | None
    vol_shock: float | None
    reason: str | None
    measurement: CrisisMeasurement | None


def crisis_values(
    session: Session, risk: RiskParams, tickers: Iterable[str], *, user_id: uuid.UUID
) -> list[CrisisValue]:
    tickers = sorted(set(tickers))
    rows = {
        (m.ticker, m.episode): m
        for m in session.scalars(
            select(CrisisMeasurement).where(
                CrisisMeasurement.user_id == user_id, CrisisMeasurement.ticker.in_(tickers)
            )
        )
    }
    out: list[CrisisValue] = []
    for ep in risk.crisis_episodes:
        for t in tickers:
            m = rows.get((t, ep.key))
            manual = risk.crisis_overrides.get(t, {}).get(ep.key)
            if manual is not None:
                out.append(
                    CrisisValue(
                        t,
                        ep.key,
                        ep.label,
                        "ok",
                        "manual",
                        manual.price_shock,
                        manual.vol_shock,
                        "choque manual da configuração",
                        m,
                    )
                )
            elif m is not None and m.status == "ok":
                stale = m.window_start is not None and not (ep.start <= m.window_start <= ep.end)
                reason = m.reason
                if stale:
                    reason = "medição de outra janela do episódio: meça de novo"
                out.append(
                    CrisisValue(
                        t,
                        ep.key,
                        ep.label,
                        "unavailable" if stale else "ok",
                        "approximate",
                        None if stale else m.price_shock,
                        None if stale else m.vol_shock,
                        reason,
                        m,
                    )
                )
            else:
                why = m.reason if m is not None else 'não medido: use "Medir cenários de crise"'
                out.append(CrisisValue(t, ep.key, ep.label, "unavailable", "approximate", None, None, why, m))
    return out


def crisis_scenarios(values: Iterable[CrisisValue]) -> list[Scenario]:
    by_ep: dict[str, dict[str, Shock]] = {}
    names: dict[str, str] = {}
    for v in values:
        names[v.episode] = v.episode
        by_ep.setdefault(v.episode, {})
        if v.status == "ok" and v.price_shock is not None and v.vol_shock is not None:
            by_ep[v.episode][v.ticker] = Shock(v.price_shock, v.vol_shock)
    return [Scenario(f"crisis_{ep}", shocks) for ep, shocks in by_ep.items()]
