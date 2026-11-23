"""Previsão de RV e avaliação de modelos (PRD 1.7 §5.7 e §7; RF-PRV-01..04, RN-PRV-01/02, CS-03).

Leitura do que o worker gravou. A única escrita é `PUT /models/selection`, que cria uma versão nova
de configuração (PRD §5.3) com o modelo do edge.
"""

import math
from datetime import date
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vollab.analytics.forecasting import forecast_interval
from vollab.analytics.market import load_holidays
from vollab.analytics.params import (
    ForecastParams,
    VolParams,
    forecast_params_from_config,
    vol_params_from_config,
)
from vollab.api.schemas.common import EstimatedValue, ProblemDetails
from vollab.api.schemas.forecast import (
    EvaluationPointOut,
    EvaluationPointsResponse,
    EvaluationResponse,
    EvaluationRow,
    EvaluationSeries,
    ForecastOut,
    ForecastsResponse,
    ModelSelectionIn,
    ModelSelectionOut,
    ModelState,
    RatioOut,
)
from vollab.collection.params import ensure_config_version
from vollab.collection.planner import today_sao_paulo
from vollab.db.config_store import create_config_version
from vollab.db.models import (
    FIXED_USER_ID,
    ConstantMaturityVol,
    ForecastEvaluation,
    ForecastEvaluationPoint,
    RealizedVol,
    RvForecast,
    Underlying,
)
from vollab.db.session import get_session
from vollab.quant.calendar import previous_business_day
from vollab.quant.forecast import ANNUALIZATION, Baseline, Model, annualized_vol, garch_term_variance
from vollab.quant.vol import Estimator
from vollab.settings import get_settings

router = APIRouter(tags=["previsão"])
SessionDep = Annotated[Session, Depends(get_session)]
NOT_FOUND: dict[int | str, dict[str, Any]] = {
    404: {"model": ProblemDetails, "description": "Ativo não cadastrado."}
}
ORDER = [m.value for m in Model] + [b.value for b in Baseline]
BASELINES = {b.value for b in Baseline}
Status = Literal["ok", "insufficient_data", "unavailable"]
Origin = Literal["observed", "estimated", "manual", "approximate"]


class _Ctx:
    def __init__(self, session: Session, ticker: str) -> None:
        ticker = ticker.upper()
        found = session.scalar(
            select(Underlying.ticker).where(Underlying.user_id == FIXED_USER_ID, Underlying.ticker == ticker)
        )
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ativo não cadastrado.")
        self.session = session
        self.ticker = ticker
        version = ensure_config_version(session, user_id=FIXED_USER_ID)
        session.commit()
        self.vol: VolParams = vol_params_from_config(version)
        self.params: ForecastParams = forecast_params_from_config(version)
        holidays = load_holidays(session)
        self.expected_as_of = previous_business_day(today_sao_paulo(get_settings()), holidays)

    def horizon(self, horizon_bd: int | None) -> int:
        return horizon_bd or self.vol.constant_maturity_bd

    def nearest_evaluated(self, h: int) -> int:
        return min(self.params.evaluation_horizons_bd, key=lambda x: (abs(x - h), x))

    def value(
        self,
        value: float | None,
        as_of: date,
        *,
        status_: str,
        origin: str = "estimated",
        reason: str | None = None,
        ci: tuple[float | None, float | None] = (None, None),
    ) -> EstimatedValue:
        ok = status_ == "ok" and value is not None
        return EstimatedValue(
            value=value if ok else None,
            ci_low=ci[0] if ok else None,
            ci_high=ci[1] if ok else None,
            ci_level=self.vol.ci_level,
            status=cast(Status, status_ if ok or status_ != "ok" else "insufficient_data"),
            origin=cast(Origin, origin),
            as_of=as_of,
            stale=as_of < self.expected_as_of,
            reason=reason,
        )


def _ctx_query(
    session: SessionDep, underlying: Annotated[str, Query(min_length=1, max_length=12, description="Ticker.")]
) -> _Ctx:
    return _Ctx(session, underlying)


CtxDep = Annotated[_Ctx, Depends(_ctx_query)]


def _evaluations(ctx: _Ctx, h: int) -> dict[str, ForecastEvaluation]:
    rows = ctx.session.scalars(
        select(ForecastEvaluation).where(
            ForecastEvaluation.ticker == ctx.ticker, ForecastEvaluation.horizon_bd == h
        )
    )
    return {r.model: r for r in rows}


def _state(model: str, state: dict[str, Any]) -> ModelState:
    out = ModelState(n_returns=state.get("n_returns"))
    if model == Model.EWMA:
        out.ewma_lambda = state.get("lambda")
    elif model == Model.COMBINATION:
        out.components = state.get("components")
        out.window_bd = state.get("window_bd")
    elif model == Model.GARCH and "omega" in state:
        omega, alpha, beta = float(state["omega"]), float(state["alpha"]), float(state["beta"])
        out.omega, out.alpha, out.beta = omega, alpha, beta
        out.persistence = alpha + beta
        out.long_run_vol = math.sqrt(ANNUALIZATION * omega / (1.0 - alpha - beta))
    return out


def _vol_from_state(model: str, state: dict[str, Any], h: int) -> float:
    """Outro horizonte a partir do estado (PRD §5.7): EWMA e combinação são planas; GARCH, eq. 4.9."""
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


def _eligibility(
    ev: ForecastEvaluation | None, min_windows: int, evaluated_h: int
) -> tuple[bool, str | None]:
    if ev is None:
        return False, "sem avaliação"
    if ev.status != "ok":
        return False, f"dados insuficientes: {ev.n_windows} de {min_windows} janelas a {evaluated_h} pregões"
    return True, None


@router.get(
    "/forecasts", response_model=ForecastsResponse, summary="RV prevista por modelo", responses=NOT_FOUND
)
def get_forecasts(
    ctx: CtxDep,
    horizon_bd: Annotated[int | None, Query(ge=1, le=252, description="Padrão: o prazo constante.")] = None,
    model: Annotated[
        Literal["ewma", "combination", "garch"] | None, Query(description="Filtra um modelo.")
    ] = None,
) -> ForecastsResponse:
    s = ctx.session
    h = ctx.horizon(horizon_bd)
    eval_h = ctx.nearest_evaluated(h)
    stored_h = h if h in ctx.params.evaluation_horizons_bd else eval_h
    evaluations = _evaluations(ctx, eval_h)
    as_of = s.scalar(select(func.max(RvForecast.as_of)).where(RvForecast.ticker == ctx.ticker))
    selected = ctx.params.selected_model
    items: list[ForecastOut] = []
    if as_of is not None:
        rows = s.scalars(
            select(RvForecast).where(
                RvForecast.ticker == ctx.ticker, RvForecast.as_of == as_of, RvForecast.horizon_bd == stored_h
            )
        ).all()
        for row in sorted(rows, key=lambda r: ORDER.index(r.model)):
            if model is not None and row.model != model:
                continue
            ev = evaluations.get(row.model)
            eligible, why = _eligibility(ev, ctx.params.min_evaluation_windows, eval_h)
            if row.status == "ok" and row.vol is not None and h != stored_h:
                vol = _vol_from_state(row.model, row.state, h)
                ci, ci_origin, ci_reason = forecast_interval(
                    vol,
                    h,
                    ctx.vol.ci_level,
                    ev,
                    min_windows=ctx.params.min_evaluation_windows,
                    evaluated_h=eval_h,
                )
                value = ctx.value(
                    vol,
                    as_of,
                    status_="ok",
                    origin=ci_origin,
                    reason=_join(row.reason, ci_reason),
                    ci=(ci.low, ci.high),
                )
            else:
                value = ctx.value(
                    row.vol,
                    as_of,
                    status_=row.status,
                    origin=row.ci_origin or "estimated",
                    reason=_join(row.reason, row.ci_reason),
                    ci=(row.ci_low, row.ci_high),
                )
            items.append(
                ForecastOut(
                    model=cast(Any, row.model),
                    kind="model",
                    forecast=value,
                    selected=row.model == selected,
                    eligible=eligible,
                    eligibility_reason=why,
                    state=_state(row.model, row.state),
                )
            )
        if model is None:
            items.extend(_baselines(ctx, as_of, h, evaluations))
    return ForecastsResponse(
        ticker=ctx.ticker,
        as_of=as_of,
        horizon_bd=h,
        evaluated_horizons_bd=ctx.params.evaluation_horizons_bd,
        selected_model=selected,
        ci_level=ctx.vol.ci_level,
        items=items,
    )


def _join(*parts: str | None) -> str | None:
    text = "; ".join(p for p in parts if p)
    return text or None


def _baselines(
    ctx: _Ctx, as_of: date, h: int, evaluations: dict[str, ForecastEvaluation]
) -> list[ForecastOut]:
    """Valor atual de cada baseline, como referência (não alimentam o edge)."""
    s = ctx.session
    official = (
        Estimator.CLOSE_TO_CLOSE
        if ctx.vol.close_to_close_mode == "zero_mean"
        else Estimator.CLOSE_TO_CLOSE_DEMEANED
    )
    rv = s.get(RealizedVol, (ctx.ticker, as_of, official.value, 20))
    c2c = (
        ctx.value(
            math.sqrt(rv.variance_annual),
            as_of,
            status_="ok",
            origin="observed",
            reason="close-to-close oficial de 20 pregões, sem correção de viés",
        )
        if rv is not None and rv.variance_annual is not None
        else ctx.value(
            None, as_of, status_="insufficient_data", reason="close-to-close de 20 pregões indisponível"
        )
    )
    if h == ctx.vol.constant_maturity_bd:
        cm = s.get(ConstantMaturityVol, (ctx.ticker, as_of, h))
        implied = (
            ctx.value(
                cm.iv, as_of, status_="ok", origin="observed", reason="IV de prazo constante, com eventos"
            )
            if cm is not None and cm.iv is not None
            else ctx.value(
                None,
                as_of,
                status_="unavailable",
                reason=(cm.reason if cm else None) or "sem IV de prazo constante",
            )
        )
    else:
        implied = ctx.value(
            None, as_of, status_="unavailable", reason="IV de prazo constante só no prazo configurado"
        )
    out = []
    for name, value in ((Baseline.RV_C2C_20.value, c2c), (Baseline.IMPLIED.value, implied)):
        eligible, why = _eligibility(
            evaluations.get(name), ctx.params.min_evaluation_windows, ctx.nearest_evaluated(h)
        )
        out.append(
            ForecastOut(
                model=cast(Any, name),
                kind="baseline",
                forecast=value,
                selected=False,
                eligible=False,
                eligibility_reason="baseline: não alimenta o edge" if eligible else why,
            )
        )
    return out


@router.get(
    "/models/evaluation",
    response_model=EvaluationResponse,
    summary="Erro de previsão por modelo × baselines",
    responses=NOT_FOUND,
)
def get_models_evaluation(
    ctx: CtxDep,
    horizon_bd: Annotated[int | None, Query(ge=1, le=252, description="Padrão: o prazo constante.")] = None,
) -> EvaluationResponse:
    h = ctx.nearest_evaluated(ctx.horizon(horizon_bd))
    evaluations = _evaluations(ctx, h)
    rows: list[EvaluationRow] = []
    any_ev = next(iter(evaluations.values()), None)
    for name in ORDER:
        ev = evaluations.get(name)
        if ev is None:
            continue
        as_of = ev.last_origin or ctx.expected_as_of
        ok = ev.status == "ok"
        rmse = ctx.value(
            ev.rmse,
            as_of,
            status_="ok" if ok else "insufficient_data",
            reason=None
            if ok
            else f"{ev.n_windows} de {ctx.params.min_evaluation_windows} janelas necessárias",
            ci=(ev.rmse_ci_low, ev.rmse_ci_high),
        )
        ratios: list[RatioOut] = []
        for baseline in (Baseline.RV_C2C_20.value, Baseline.IMPLIED.value):
            r = ev.ratios.get(baseline)
            if r is None:
                continue
            r_ok = r.get("status") == "ok"
            ratios.append(
                RatioOut(
                    baseline=cast(Any, baseline),
                    n_windows=int(r.get("n", 0)),
                    ratio=ctx.value(
                        r.get("value"),
                        as_of,
                        status_="ok" if r_ok else "insufficient_data",
                        reason=None
                        if r_ok
                        else f"{r.get('n', 0)} de {ctx.params.min_evaluation_windows} janelas pareadas",
                        ci=(r.get("ci_low"), r.get("ci_high")),
                    ),
                )
            )
        rows.append(
            EvaluationRow(
                model=cast(Any, name),
                kind="baseline" if name in BASELINES else "model",
                status=cast(Any, ev.status),
                n_windows=ev.n_windows,
                discarded_no_forecast=int(ev.discarded.get("no_forecast", 0)),
                discarded_incomplete_realized=int(ev.discarded.get("incomplete_realized", 0)),
                first_origin=ev.first_origin,
                last_origin=ev.last_origin,
                bias=ev.bias if ok else None,
                mae=ev.mae if ok else None,
                rmse=rmse,
                ratios=ratios,
            )
        )
    return EvaluationResponse(
        ticker=ctx.ticker,
        horizon_bd=h,
        evaluated_horizons_bd=ctx.params.evaluation_horizons_bd,
        min_windows=ctx.params.min_evaluation_windows,
        ci_level=ctx.vol.ci_level,
        selected_model=ctx.params.selected_model,
        computed_at=any_ev.computed_at if any_ev else None,
        config_version_id=any_ev.config_version_id if any_ev else None,
        engine_version=any_ev.engine_version if any_ev else None,
        rows=rows,
    )


@router.get(
    "/models/evaluation/points",
    response_model=EvaluationPointsResponse,
    summary="Previsto × realizado por janela não sobreposta",
    responses=NOT_FOUND,
)
def get_models_evaluation_points(
    ctx: CtxDep,
    horizon_bd: Annotated[int | None, Query(ge=1, le=252, description="Padrão: o prazo constante.")] = None,
    model: Annotated[
        Literal["ewma", "combination", "garch", "rv_c2c_20", "implied"] | None,
        Query(description="Padrão: todos."),
    ] = None,
) -> EvaluationPointsResponse:
    h = ctx.nearest_evaluated(ctx.horizon(horizon_bd))
    stmt = select(ForecastEvaluationPoint).where(
        ForecastEvaluationPoint.ticker == ctx.ticker, ForecastEvaluationPoint.horizon_bd == h
    )
    if model is not None:
        stmt = stmt.where(ForecastEvaluationPoint.model == model)
    evaluations = _evaluations(ctx, h)
    grouped: dict[str, list[EvaluationPointOut]] = {}
    origins: dict[str, str] = {}
    for p in ctx.session.scalars(stmt.order_by(ForecastEvaluationPoint.origin)):
        lo = hi = None
        if p.forecast is not None:
            ci, origins[p.model], _ = forecast_interval(
                p.forecast,
                h,
                ctx.vol.ci_level,
                evaluations.get(p.model),
                min_windows=ctx.params.min_evaluation_windows,
            )
            lo, hi = ci.low, ci.high
        grouped.setdefault(p.model, []).append(
            EvaluationPointOut(
                origin=p.origin,
                window_end=p.window_end,
                forecast=p.forecast,
                forecast_ci_low=lo,
                forecast_ci_high=hi,
                realized=p.realized,
                discard_reason=cast(Any, p.discard_reason),
            )
        )
    series = [
        EvaluationSeries(
            model=cast(Any, m), ci_origin=cast(Any, origins.get(m, "approximate")), points=grouped[m]
        )
        for m in ORDER
        if m in grouped
    ]
    return EvaluationPointsResponse(ticker=ctx.ticker, horizon_bd=h, series=series)


@router.put(
    "/models/selection",
    response_model=ModelSelectionOut,
    summary="Escolher o modelo do edge (RF-PRV-04)",
    responses={409: {"model": ProblemDetails, "description": "Modelo sem avaliação disponível."}},
)
def put_model_selection(body: ModelSelectionIn, session: SessionDep) -> ModelSelectionOut:
    version = ensure_config_version(session, user_id=FIXED_USER_ID)
    params = forecast_params_from_config(version)
    if params.selected_model == body.model:
        session.commit()
        return ModelSelectionOut(selected_model=body.model, config_version_id=version.id, created=False)
    # RF-PRV-02: só um modelo com avaliação disponível (em algum ativo, no prazo do edge) pode ser escolhido.
    h = vol_params_from_config(version).constant_maturity_bd
    eval_h = min(params.evaluation_horizons_bd, key=lambda x: (abs(x - h), x))
    available = session.scalar(
        select(func.count())
        .select_from(ForecastEvaluation)
        .join(Underlying, Underlying.ticker == ForecastEvaluation.ticker)
        .where(
            Underlying.user_id == FIXED_USER_ID,
            Underlying.active.is_(True),
            ForecastEvaluation.model == body.model,
            ForecastEvaluation.horizon_bd == eval_h,
            ForecastEvaluation.status == "ok",
        )
    )
    if not available:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"O modelo {body.model} não tem avaliação disponível em nenhum ativo a {eval_h} pregões "
            f"(mínimo de {params.min_evaluation_windows} janelas).",
        )
    new_params = dict(version.params)
    new_params["forecast"] = params.model_copy(update={"selected_model": body.model}).model_dump(mode="json")
    created = create_config_version(
        session, user_id=FIXED_USER_ID, params=new_params, note=f"Modelo do edge: {body.model} (RF-PRV-04)."
    )
    session.commit()
    return ModelSelectionOut(selected_model=body.model, config_version_id=created.id, created=True)
