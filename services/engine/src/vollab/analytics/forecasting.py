"""Previsão de RV e avaliação de modelos no worker (PRD 1.7 §5.7; RF-PRV-01..04, RN-PRV-01/02).

Job `forecast_recompute`, enfileirado ao fim de cada `vol_recompute`. Para cada ativo:

1. retornos diários ajustados (RN-VOL-07) e estimadores de RV da janela da combinação;
2. previsões de EWMA e combinação em todo pregão; GARCH(1,1) nas origens da avaliação e no último
   pregão (o ajuste é o passo caro);
3. avaliação em janelas não sobrepostas, ancoradas no fim, contra os baselines RV close-to-close de
   20 pregões e IV de prazo constante (RF-PRV-03, RN-PRV-01);
4. intervalo de cada previsão: empírico pelos quantis do erro avaliado, ou χ² (QA-07).

Idempotente: apaga e regrava tudo do ativo (só agregados diários; barato). As telas só leem.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
import structlog
from numpy.typing import NDArray
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from vollab.analytics.market import (
    active_tickers,
    load_daily_series,
    load_dividends,
    load_holidays,
    load_intraday_variance,
)
from vollab.analytics.params import (
    ForecastParams,
    VolParams,
    forecast_params_from_config,
    vol_params_from_config,
)
from vollab.collection.params import ensure_config_version
from vollab.db.models import (
    FIXED_USER_ID,
    ConstantMaturityVol,
    ForecastEvaluation,
    ForecastEvaluationPoint,
    Job,
    JobStatus,
    RvForecast,
)
from vollab.jobs import queue
from vollab.jobs.handlers import register
from vollab.quant.forecast import (
    ANNUALIZATION,
    RECOMMENDED_GARCH_RETURNS,
    Baseline,
    GarchFailure,
    GarchFit,
    Interval,
    Model,
    annualized_vol,
    chi2_forecast_interval,
    combination_variance,
    empirical_forecast_interval,
    error_metrics,
    ewma_path,
    fit_garch,
    garch_term_variance,
    log_error_quantiles,
    non_overlapping_origins,
    realized_vol,
    rmse_interval,
    rmse_ratio,
)
from vollab.quant.vol import Estimator, daily_terms, rolling
from vollab.settings import get_settings

log = structlog.get_logger("vollab.forecast")

JOB_KIND = "forecast_recompute"
BOOTSTRAP_SEED = 20261123
BASELINE_WINDOW_BD = 20
_BATCH = 2000

NO_FORECAST = "no_forecast"
INCOMPLETE_REALIZED = "incomplete_realized"


def enqueue_forecast(session: Session, *, user_id: uuid.UUID, tickers: list[str] | None, reason: str) -> None:
    """Enfileira a previsão; não duplica um pedido igual que ainda está na fila."""
    payload: dict[str, Any] = {"user_id": str(user_id), "reason": reason}
    if tickers:
        payload["tickers"] = sorted(set(tickers))
    queued = session.scalars(select(Job).where(Job.kind == JOB_KIND, Job.status == JobStatus.QUEUED)).all()
    for job in queued:
        if job.payload.get("tickers") is None or job.payload.get("tickers") == payload.get("tickers"):
            return
    queue.enqueue(session, user_id=user_id, kind=JOB_KIND, payload=payload, max_attempts=3)


@register(JOB_KIND)
def run_forecast_job(session: Session, payload: dict[str, Any]) -> None:
    user_id = uuid.UUID(str(payload.get("user_id") or FIXED_USER_ID))
    tickers = payload.get("tickers")
    version = ensure_config_version(session, user_id=user_id)
    session.commit()
    ForecastComputer(
        session,
        version_id=version.id,
        vol=vol_params_from_config(version),
        forecast=forecast_params_from_config(version),
    ).run(list(tickers) if isinstance(tickers, list) else None)
    # Etapa 7: a marcação D-1 das operações vem depois dos dados do pregão (PRD 1.10 §5.9).
    from vollab.analytics.journal import enqueue_marks

    enqueue_marks(session, user_id=user_id, position_ids=None, reason="forecast_recompute")
    session.commit()


@dataclass(slots=True)
class _Point:
    """Previsão de um modelo numa origem (vol anualizada) ou o motivo da ausência."""

    vol: float | None
    status: str  # ok | insufficient_data | unavailable
    reason: str | None = None
    state: dict[str, Any] = field(default_factory=dict)


class ForecastComputer:
    def __init__(
        self,
        session: Session,
        *,
        version_id: int,
        vol: VolParams,
        forecast: ForecastParams,
        engine_version: str | None = None,
    ) -> None:
        self.session = session
        self.version_id = version_id
        self.vol = vol
        self.params = forecast
        self.engine_version = engine_version or get_settings().engine_version
        self.holidays = load_holidays(session)

    def run(self, tickers: list[str] | None) -> None:
        for ticker in tickers or active_tickers(self.session):
            self.ticker(ticker)
            self.session.commit()

    # Um ativo -------------------------------------------------------------------------------

    def ticker(self, ticker: str) -> None:
        s = self.session
        for table in (RvForecast, ForecastEvaluation, ForecastEvaluationPoint):
            s.execute(delete(table).where(table.ticker == ticker))
        series = load_daily_series(s, ticker, self.holidays, load_dividends(s, ticker))
        if series is None or len(series.days) < 2:
            return
        days = series.days
        n = len(days)
        terms = daily_terms(series.open, series.high, series.low, series.close, series.prev_close_adj)
        r = terms.ret_cc
        official = (
            Estimator.CLOSE_TO_CLOSE
            if self.vol.close_to_close_mode == "zero_mean"
            else Estimator.CLOSE_TO_CLOSE_DEMEANED
        )
        p = self.params

        # Combinação (PRD §5.7): close-to-close oficial, Yang-Zhang e Rogers-Satchell obrigatórios,
        # intradiária onde existir; Parkinson e Garman-Klass fora (RN-VOL-09).
        w = p.combination_window_bd
        required = {
            official.value: rolling(official, terms, w).variance_annual,
            Estimator.YANG_ZHANG.value: rolling(Estimator.YANG_ZHANG, terms, w).variance_annual,
            Estimator.ROGERS_SATCHELL.value: rolling(Estimator.ROGERS_SATCHELL, terms, w).variance_annual,
        }
        intraday = load_intraday_variance(s, ticker, series)
        optional: dict[str, NDArray[np.float64]] = {}
        if intraday.first_index is not None:
            optional[Estimator.INTRADAY_5M.value] = rolling(
                Estimator.INTRADAY_5M, terms, w, intraday_var=intraday.variance
            ).variance_annual
        comb_annual, _ = combination_variance(list(required.values()), list(optional.values()))
        baseline_c2c = rolling(official, terms, BASELINE_WINDOW_BD).variance_annual

        ewma = ewma_path(r, p.ewma_lambda)
        valid_idx = np.flatnonzero(np.isfinite(r))
        cm_iv = self._constant_maturity(ticker)

        garch_cache: dict[int, GarchFit | GarchFailure] = {}

        def garch_fit(t: int) -> GarchFit | GarchFailure:
            if t not in garch_cache:
                used = r[valid_idx[valid_idx <= t]][-p.garch_max_returns :]
                garch_cache[t] = fit_garch(used, min_returns=p.garch_min_returns)
            return garch_cache[t]

        def model_point(model: Model, t: int, h: int) -> _Point:
            match model:
                case Model.EWMA:
                    k = int(ewma.n_returns[t])
                    v = float(ewma.next_var[t])
                    if k < p.ewma_min_returns or not math.isfinite(v):
                        return _Point(
                            None, "insufficient_data", f"{k} retornos; mínimo de {p.ewma_min_returns}"
                        )
                    state: dict[str, Any] = {"lambda": p.ewma_lambda, "next_var": v, "n_returns": k}
                    return _Point(annualized_vol(v), "ok", state=state)
                case Model.COMBINATION:
                    va = float(comb_annual[t])
                    if not math.isfinite(va):
                        return _Point(
                            None,
                            "insufficient_data",
                            "close-to-close, Yang-Zhang ou Rogers-Satchell indisponível "
                            f"na janela de {w} pregões",
                        )
                    components = [k for k, arr in required.items() if math.isfinite(arr[t])]
                    components += [k for k, arr in optional.items() if math.isfinite(arr[t])]
                    state = {
                        "next_var": va / ANNUALIZATION,
                        "components": components,
                        "window_bd": w,
                        "n_returns": int(ewma.n_returns[t]),
                    }
                    return _Point(math.sqrt(va), "ok", state=state)
                case Model.GARCH:
                    fit = garch_fit(t)
                    if isinstance(fit, GarchFailure):
                        status = "insufficient_data" if fit.n_returns < p.garch_min_returns else "unavailable"
                        return _Point(None, status, fit.reason, {"n_returns": fit.n_returns})
                    reason = None
                    if fit.n_returns < RECOMMENDED_GARCH_RETURNS:
                        reason = (
                            f"estimado com {fit.n_returns} retornos; a referência recomenda "
                            f"≥ {RECOMMENDED_GARCH_RETURNS}"
                        )
                    state = {
                        "omega": fit.omega,
                        "alpha": fit.alpha,
                        "beta": fit.beta,
                        "next_var": fit.next_var,
                        "loglik": fit.loglik,
                        "n_returns": fit.n_returns,
                    }
                    var = garch_term_variance(fit.next_var, fit.omega, fit.alpha, fit.beta, h)
                    return _Point(annualized_vol(var), "ok", reason, state)

        def baseline_point(baseline: Baseline, t: int, h: int) -> _Point:
            if baseline is Baseline.RV_C2C_20:
                va = float(baseline_c2c[t])
                return _Point(math.sqrt(va), "ok") if math.isfinite(va) else _Point(None, "insufficient_data")
            if h != self.vol.constant_maturity_bd:
                return _Point(None, "unavailable", "IV de prazo constante só no prazo configurado")
            iv = cm_iv.get(days[t])
            return _Point(iv, "ok") if iv is not None else _Point(None, "insufficient_data")

        evaluations: dict[tuple[str, int], ForecastEvaluation] = {}
        point_rows: list[dict[str, Any]] = []
        garch_days: set[int] = {n - 1}
        for h in p.evaluation_horizons_bd:
            origins = non_overlapping_origins(n, h)
            realized = [realized_vol(r, t, h) for t in origins]
            by_name: dict[str, list[float | None]] = {}
            for m in Model:
                if m is Model.GARCH:
                    garch_days.update(origins)
                by_name[m.value] = [model_point(m, t, h).vol for t in origins]
            for b in Baseline:
                by_name[b.value] = [baseline_point(b, t, h).vol for t in origins]
            for name, forecasts in by_name.items():
                for t, f, rv in zip(origins, forecasts, realized, strict=True):
                    reason = NO_FORECAST if f is None else INCOMPLETE_REALIZED if rv is None else None
                    point_rows.append(
                        {
                            "ticker": ticker,
                            "model": name,
                            "horizon_bd": h,
                            "origin": days[t],
                            "window_end": days[t + h],
                            "forecast": f,
                            "realized": rv,
                            "discard_reason": reason,
                        }
                    )
                evaluations[(name, h)] = self._evaluate(
                    ticker, name, h, origins, days, forecasts, realized, by_name
                )

        # Previsões gravadas: EWMA e combinação em todo pregão com valor; GARCH nas origens e no último
        # pregão; o último pregão sempre tem uma linha por modelo (mesmo sem número, com o motivo).
        rows: list[dict[str, Any]] = []
        for h in p.evaluation_horizons_bd:
            for m in Model:
                ev = evaluations[(m.value, h)]
                idxs = sorted(garch_days) if m is Model.GARCH else range(n)
                for t in idxs:
                    pt = model_point(m, t, h)
                    if pt.status != "ok" and t != n - 1:
                        continue
                    rows.append(self._forecast_row(ticker, days[t], m, h, pt, ev))
        for start in range(0, len(rows), _BATCH):
            s.execute(insert(RvForecast), rows[start : start + _BATCH])
        for start in range(0, len(point_rows), _BATCH):
            s.execute(insert(ForecastEvaluationPoint), point_rows[start : start + _BATCH])
        s.add_all(evaluations.values())
        log.info(
            "forecast.recomputed",
            ticker=ticker,
            forecasts=len(rows),
            garch_fits=len(garch_cache),
            evaluations={f"{k[0]}@{k[1]}": v.n_windows for k, v in evaluations.items()},
        )

    def _constant_maturity(self, ticker: str) -> dict[date, float]:
        rows = self.session.execute(
            select(ConstantMaturityVol.as_of, ConstantMaturityVol.iv).where(
                ConstantMaturityVol.ticker == ticker,
                ConstantMaturityVol.target_bd == self.vol.constant_maturity_bd,
                ConstantMaturityVol.status == "ok",
            )
        )
        return {d: float(iv) for d, iv in rows if iv is not None}

    # Avaliação ------------------------------------------------------------------------------

    def _evaluate(
        self,
        ticker: str,
        name: str,
        h: int,
        origins: list[int],
        days: list[date],
        forecasts: list[float | None],
        realized: list[float | None],
        by_name: dict[str, list[float | None]],
    ) -> ForecastEvaluation:
        p = self.params
        level = self.vol.ci_level
        used = [
            (t, f, rv)
            for t, f, rv in zip(origins, forecasts, realized, strict=True)
            if f is not None and rv is not None
        ]
        discarded = {
            NO_FORECAST: sum(1 for f in forecasts if f is None),
            INCOMPLETE_REALIZED: sum(
                1 for f, rv in zip(forecasts, realized, strict=True) if f is not None and rv is None
            ),
        }
        ok = len(used) >= p.min_evaluation_windows
        ev = ForecastEvaluation(
            ticker=ticker,
            model=name,
            horizon_bd=h,
            n_windows=len(used),
            discarded=discarded,
            ratios={},
            status="ok" if ok else "insufficient_data",
            ci_level=level,
            first_origin=days[used[0][0]] if used else None,
            last_origin=days[used[-1][0]] if used else None,
            config_version_id=self.version_id,
            engine_version=self.engine_version,
        )
        if ok:
            f_arr = np.array([u[1] for u in used])
            rv_arr = np.array([u[2] for u in used])
            m = error_metrics(f_arr, rv_arr)
            ci = rmse_interval(f_arr, rv_arr, reps=p.bootstrap_reps, level=level, seed=BOOTSTRAP_SEED)
            q = log_error_quantiles(f_arr, rv_arr, level)
            ev.bias, ev.mae, ev.rmse = m.bias, m.mae, m.rmse
            ev.rmse_ci_low, ev.rmse_ci_high = ci.low, ci.high
            ev.log_q_low, ev.log_q_high = q.low, q.high
        ratios: dict[str, Any] = {}
        for b in Baseline:
            if b.value == name:
                continue
            pairs = [
                (f, bf, rv)
                for f, bf, rv in zip(forecasts, by_name[b.value], realized, strict=True)
                if f is not None and bf is not None and rv is not None
            ]
            entry: dict[str, Any] = {"n": len(pairs), "status": "insufficient_data"}
            if len(pairs) >= p.min_evaluation_windows:
                arr = np.array(pairs)
                value, rci = rmse_ratio(
                    arr[:, 0], arr[:, 1], arr[:, 2], reps=p.bootstrap_reps, level=level, seed=BOOTSTRAP_SEED
                )
                if math.isfinite(value):
                    entry = {
                        "n": len(pairs),
                        "status": "ok",
                        "value": value,
                        "ci_low": rci.low,
                        "ci_high": rci.high,
                    }
            ratios[b.value] = entry
        ev.ratios = ratios
        return ev

    def _forecast_row(
        self, ticker: str, as_of: date, model: Model, h: int, pt: _Point, ev: ForecastEvaluation
    ) -> dict[str, Any]:
        ci: Interval | None = None
        ci_origin = ci_reason = None
        if pt.vol is not None:
            ci, ci_origin, ci_reason = forecast_interval(
                pt.vol, h, self.vol.ci_level, ev, min_windows=self.params.min_evaluation_windows
            )
        return {
            "ticker": ticker,
            "as_of": as_of,
            "model": model.value,
            "horizon_bd": h,
            "vol": pt.vol,
            "ci_low": ci.low if ci else None,
            "ci_high": ci.high if ci else None,
            "ci_origin": ci_origin,
            "ci_reason": ci_reason,
            "status": pt.status,
            "reason": pt.reason,
            "state": pt.state,
            "config_version_id": self.version_id,
            "engine_version": self.engine_version,
        }


def forecast_interval(
    vol: float,
    h: int,
    level: float,
    ev: ForecastEvaluation | None,
    *,
    min_windows: int,
    evaluated_h: int | None = None,
) -> tuple[Interval, str, str | None]:
    """Intervalo da previsão (QA-07): empírico com a avaliação disponível; senão χ² em h dias.

    `evaluated_h` ≠ h: os quantis vêm de outro horizonte avaliado (leitura de horizonte livre) e o
    intervalo fica `approximate`. Nas linhas históricas os quantis são os da avaliação inteira
    (inclui janelas posteriores): servem à exibição, não à avaliação."""
    if ev is not None and ev.status == "ok" and ev.log_q_low is not None and ev.log_q_high is not None:
        ci = empirical_forecast_interval(vol, Interval(ev.log_q_low, ev.log_q_high))
        if evaluated_h is not None and evaluated_h != h:
            return ci, "approximate", f"intervalo do horizonte avaliado de {evaluated_h} pregões"
        return ci, "estimated", None
    return (
        chi2_forecast_interval(vol, h, level),
        "approximate",
        f"intervalo só com o erro de amostragem (< {min_windows} janelas avaliadas)",
    )


def vol_from_state(model: str, state: dict[str, Any], h: int) -> float:
    """Previsão em outro horizonte a partir do estado gravado (PRD §5.7): EWMA e combinação são
    planas; GARCH pela eq. 4.9 a partir de σ²ₜ₊₁."""
    if model == Model.GARCH:
        return annualized_vol(
            garch_term_variance(
                float(state["next_var"]),
                float(state["omega"]),
                float(state["alpha"]),
                float(state["beta"]),
                h,
            )
        )
    return annualized_vol(float(state["next_var"]))
