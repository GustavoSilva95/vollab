"""Previsão de volatilidade realizada e avaliação de modelos (RF-PRV-01..04, RN-PRV-01/02; PRD §5.7).

Puro, sem I/O. Fórmulas conforme a referência técnica (`docs/referencia/volatility-trading.md`,
§3 Cap. 4): EWMA (eq. 4.1), GARCH(1,1) (eqs. 4.4, 4.5 e 4.9).

Convenções (PRD §5.1 e §5.7):
- retornos diários rₜ = ln(Cₜ / (Cₜ₋₁ − D)), ajustados por proventos, **média zero**; NaN = pregão
  sem retorno válido (não entra em nenhuma conta);
- variâncias diárias em decimal; vol anualizada = √(252 · variância diária);
- σ̂(t, h) = vol anualizada média esperada nos pregões t+1 … t+h, usando só dados até t;
- alvo da avaliação: close-to-close de média zero nos h pregões seguintes, sem correção de viés.
"""

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.stats import chi2

ANNUALIZATION = 252

FloatArray = NDArray[np.float64]


class Model(StrEnum):
    """Modelos de previsão (RF-PRV-02). Nomes gravados em `rv_forecasts.model`."""

    EWMA = "ewma"
    COMBINATION = "combination"
    GARCH = "garch"


class Baseline(StrEnum):
    """Baselines da avaliação (RF-PRV-03)."""

    RV_C2C_20 = "rv_c2c_20"
    IMPLIED = "implied"


def annualized_vol(daily_variance: float) -> float:
    return math.sqrt(ANNUALIZATION * daily_variance)


# --- EWMA (eq. 4.1) ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EwmaPath:
    """Por pregão i: `next_var[i]` = variância diária prevista para i+1 feita no fim de i (usa só
    r[0..i]); `n_returns[i]` = retornos válidos usados até i. NaN antes da inicialização."""

    next_var: FloatArray
    n_returns: NDArray[np.int64]


def ewma_path(returns: ArrayLike, lam: float, *, init_n: int = 20) -> EwmaPath:
    """v ← λ·v + (1 − λ)·r² a cada retorno válido (eq. 4.1), iniciada pela média de r² dos `init_n`
    primeiros retornos válidos. Pregões sem retorno válido repetem a variância anterior."""
    if not 0 < lam < 1:
        raise ValueError("λ deve estar em (0, 1).")
    r = np.asarray(returns, dtype=np.float64)
    out = np.full(r.shape, np.nan)
    counts = np.zeros(r.shape, dtype=np.int64)
    v = math.nan
    seen = 0
    acc = 0.0
    for i, x in enumerate(r):
        if math.isfinite(x):
            seen += 1
            if seen < init_n:
                acc += x * x
            elif seen == init_n:
                v = (acc + x * x) / init_n
            else:
                v = lam * v + (1.0 - lam) * x * x
        counts[i] = seen
        out[i] = v
    return EwmaPath(next_var=out, n_returns=counts)


# --- GARCH(1,1) (eqs. 4.4, 4.5, 4.9) ---------------------------------------------------------

# Persistência máxima aceita: acima disso o processo é praticamente integrado (IGARCH) e a variância
# de longo prazo V = ω/(1 − α − β) não é confiável (PRD §5.7).
MAX_PERSISTENCE = 0.999
# A referência recomenda ≥ ~1.000 pontos (cap. 4); abaixo disso o motivo fica registrado (LC-04).
RECOMMENDED_GARCH_RETURNS = 1000
# Escala numérica do ajuste: retornos em % (a `arch` converge melhor com variâncias perto de 1).
_GARCH_SCALE = 100.0


@dataclass(frozen=True, slots=True)
class GarchFit:
    """Parâmetros na escala de retornos decimais diários."""

    omega: float
    alpha: float
    beta: float
    next_var: float  # σ²ₜ₊₁ = ω + α·rₜ² + β·σ²ₜ, conhecido em t
    n_returns: int
    loglik: float

    @property
    def persistence(self) -> float:
        return self.alpha + self.beta

    @property
    def long_run_var(self) -> float:
        """V = ω / (1 − α − β) (eq. 4.5)."""
        return self.omega / (1.0 - self.persistence)


@dataclass(frozen=True, slots=True)
class GarchFailure:
    reason: str
    n_returns: int


def fit_garch(returns: ArrayLike, *, min_returns: int) -> GarchFit | GarchFailure:
    """GARCH(1,1) de média zero e inovação normal, por máxima verossimilhança (biblioteca `arch`).

    `returns` são só os retornos válidos, em ordem, até a origem (sem NaN)."""
    r = np.asarray(returns, dtype=np.float64)
    n = int(r.size)
    if n < min_returns:
        return GarchFailure(f"{n} retornos; mínimo de {min_returns}", n)
    if not np.all(np.isfinite(r)):
        raise ValueError("fit_garch recebe só retornos válidos.")
    from arch import arch_model  # import tardio: a `arch` puxa pandas e statsmodels

    model = arch_model(r * _GARCH_SCALE, mean="zero", vol="garch", p=1, q=1, dist="normal", rescale=False)
    try:
        res = model.fit(disp="off", show_warning=False)
    except (ValueError, np.linalg.LinAlgError) as exc:
        return GarchFailure(f"ajuste falhou ({type(exc).__name__})", n)
    if res.convergence_flag != 0:
        return GarchFailure("o ajuste não convergiu", n)
    scale2 = _GARCH_SCALE**2
    omega = float(res.params["omega"]) / scale2
    alpha = float(res.params["alpha[1]"])
    beta = float(res.params["beta[1]"])
    if not (omega > 0 and 0 <= alpha < 1 and 0 <= beta < 1):
        return GarchFailure("parâmetros fora do domínio (ω > 0, 0 ≤ α, β < 1)", n)
    if alpha + beta >= MAX_PERSISTENCE:
        return GarchFailure(f"persistência α + β = {alpha + beta:.4f} ≥ {MAX_PERSISTENCE}", n)
    sigma2_t = float(np.asarray(res.conditional_volatility)[-1]) ** 2 / scale2
    next_var = omega + alpha * float(r[-1]) ** 2 + beta * sigma2_t
    return GarchFit(omega, alpha, beta, next_var, n, float(res.loglikelihood))


def garch_term_variance(next_var: float, omega: float, alpha: float, beta: float, horizon: int) -> float:
    """Média das variâncias diárias previstas para τ = 1…h:

    E[σ²ₜ₊τ] = V + (α + β)^(τ−1)·(σ²ₜ₊₁ − V), que é a eq. 4.9 escrita a partir de σ²ₜ₊₁.
    Soma geométrica fechada: V + (σ²ₜ₊₁ − V)·(1 − pʰ)/((1 − p)·h), p = α + β.
    """
    if horizon < 1:
        raise ValueError("Horizonte ≥ 1 pregão.")
    p = alpha + beta
    if not 0 <= p < 1:
        raise ValueError("Exige 0 ≤ α + β < 1.")
    v_long = omega / (1.0 - p)
    return v_long + (next_var - v_long) * (1.0 - p**horizon) / ((1.0 - p) * horizon)


# --- Combinação de estimadores ---------------------------------------------------------------


def combination_variance(
    required: Sequence[ArrayLike], optional: Sequence[ArrayLike] = ()
) -> tuple[FloatArray, NDArray[np.int64]]:
    """Média simples das variâncias (mesma escala) por pregão (PRD §5.7).

    `required` (close-to-close oficial, Yang-Zhang, Rogers-Satchell): todos precisam existir no
    pregão; `optional` (intradiária): entra só onde existe. Devolve (variância, nº de componentes)."""
    req = np.vstack([np.asarray(x, dtype=np.float64) for x in required])
    ok = np.all(np.isfinite(req), axis=0)
    total = np.where(ok, req.sum(axis=0), np.nan)
    count = np.where(ok, req.shape[0], 0).astype(np.int64)
    for x in optional:
        arr = np.asarray(x, dtype=np.float64)
        has = ok & np.isfinite(arr)
        total = np.where(has, total + np.where(has, arr, 0.0), total)
        count = count + has.astype(np.int64)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count > 0, total / np.maximum(count, 1), np.nan), count


# --- Avaliação (RN-PRV-01, T-REF-09) ----------------------------------------------------------


def non_overlapping_origins(n_days: int, horizon: int, *, first: int = 0) -> list[int]:
    """Índices de origem, ancorados no fim: a última origem t_K = n_days − 1 − h (a janela realizada
    (t_K, t_K + h] termina no último pregão); as anteriores recuam de h em h até `first`.

    As janelas realizadas (tₖ, tₖ + h] são disjuntas: nenhum pregão aparece em duas."""
    if horizon < 1:
        raise ValueError("Horizonte ≥ 1 pregão.")
    last = n_days - 1 - horizon
    if last < first:
        return []
    return list(range(last, first - 1, -horizon))[::-1]


def realized_vol(returns: ArrayLike, origin: int, horizon: int) -> float | None:
    """√((252/h)·Σᵢ₌₁..ₕ r²ₜ₊ᵢ); None se faltar qualquer retorno da janela."""
    r = np.asarray(returns, dtype=np.float64)[origin + 1 : origin + 1 + horizon]
    if r.size != horizon or not np.all(np.isfinite(r)):
        return None
    return math.sqrt(ANNUALIZATION / horizon * float(np.sum(r * r)))


@dataclass(frozen=True, slots=True)
class Interval:
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class ErrorMetrics:
    n: int
    bias: float  # média de (σ̂ − RV), pontos de vol em decimal
    mae: float
    rmse: float


def error_metrics(forecast: ArrayLike, realized: ArrayLike) -> ErrorMetrics:
    f = np.asarray(forecast, dtype=np.float64)
    rv = np.asarray(realized, dtype=np.float64)
    if f.shape != rv.shape or f.size == 0:
        raise ValueError("Previsões e realizadas pareadas, ao menos uma.")
    e = f - rv
    return ErrorMetrics(
        n=int(e.size),
        bias=float(np.mean(e)),
        mae=float(np.mean(np.abs(e))),
        rmse=math.sqrt(float(np.mean(e * e))),
    )


def _rmse_rows(e: FloatArray) -> FloatArray:
    return np.sqrt(np.mean(e * e, axis=-1))


def bootstrap_interval(
    statistic: Callable[[NDArray[np.int64]], FloatArray],
    n: int,
    *,
    reps: int,
    level: float,
    seed: int,
) -> Interval:
    """Bootstrap percentil: `statistic` recebe uma matriz (reps × n) de índices reamostrados e devolve
    um valor por linha. Semente fixa: o mesmo dado sempre dá o mesmo intervalo."""
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(reps, n))
    values = statistic(idx)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("Nenhuma reamostragem válida.")
    a = (1.0 - level) / 2.0
    lo, hi = np.quantile(values, [a, 1.0 - a])
    return Interval(float(lo), float(hi))


def rmse_interval(
    forecast: ArrayLike, realized: ArrayLike, *, reps: int, level: float, seed: int
) -> Interval:
    e = np.asarray(forecast, dtype=np.float64) - np.asarray(realized, dtype=np.float64)
    return bootstrap_interval(lambda idx: _rmse_rows(e[idx]), e.size, reps=reps, level=level, seed=seed)


def rmse_ratio(
    forecast: ArrayLike, baseline: ArrayLike, realized: ArrayLike, *, reps: int, level: float, seed: int
) -> tuple[float, Interval]:
    """RMSE(modelo) / RMSE(baseline) nas mesmas origens (pareadas), com intervalo bootstrap. < 1 =
    o modelo erra menos que o baseline."""
    rv = np.asarray(realized, dtype=np.float64)
    em = np.asarray(forecast, dtype=np.float64) - rv
    eb = np.asarray(baseline, dtype=np.float64) - rv
    value = math.sqrt(float(np.mean(em * em))) / math.sqrt(float(np.mean(eb * eb)))

    def stat(idx: NDArray[np.int64]) -> FloatArray:
        with np.errstate(divide="ignore", invalid="ignore"):
            return _rmse_rows(em[idx]) / _rmse_rows(eb[idx])

    return value, bootstrap_interval(stat, rv.size, reps=reps, level=level, seed=seed)


# --- Intervalos (QA-07) -----------------------------------------------------------------------


def log_error_quantiles(forecast: ArrayLike, realized: ArrayLike, level: float) -> Interval:
    """Quantis de ln(RV/σ̂) nas janelas avaliadas (5% e 95% a 90%)."""
    le = np.log(np.asarray(realized, dtype=np.float64) / np.asarray(forecast, dtype=np.float64))
    a = (1.0 - level) / 2.0
    lo, hi = np.quantile(le, [a, 1.0 - a])
    return Interval(float(lo), float(hi))


def empirical_forecast_interval(forecast: float, quantiles: Interval) -> Interval:
    """[σ̂·e^q_low, σ̂·e^q_high] (PRD §5.7, QA-07)."""
    return Interval(forecast * math.exp(quantiles.low), forecast * math.exp(quantiles.high))


def chi2_forecast_interval(forecast: float, horizon: int, level: float) -> Interval:
    """Fallback analítico: só o erro de amostragem da RV em h dias, supondo o modelo correto.

    h·RV²/σ̂² ~ χ²ₕ ⇒ RV ∈ [σ̂·√(χ²ₕ(a)/h), σ̂·√(χ²ₕ(1 − a)/h)], a = (1 − nível)/2."""
    lo, hi = _chi2_quantiles(horizon, level)
    return Interval(forecast * math.sqrt(lo / horizon), forecast * math.sqrt(hi / horizon))


def chi2_vol_interval(sample_vol: float, dof: int, level: float) -> Interval:
    """Intervalo para σ a partir da vol amostral s (sem correção de viés), retornos normais:
    dof·s²/σ² ~ χ²_dof ⇒ σ ∈ [s·√(dof/χ²(1 − a)), s·√(dof/χ²(a))].

    Close-to-close de média zero: dof = n (s² = Σr²/n); com média subtraída: dof = n − 1 (s² com
    divisor n − 1)."""
    lo, hi = _chi2_quantiles(dof, level)
    return Interval(sample_vol * math.sqrt(dof / hi), sample_vol * math.sqrt(dof / lo))


@lru_cache(maxsize=256)
def _chi2_quantiles(dof: int, level: float) -> tuple[float, float]:
    """Quantis (a, 1 − a) do χ²_dof, a = (1 − nível)/2. Em cache: a mesma (dof, nível) se repete em
    todas as linhas de um ativo (revisão de performance da Etapa 4, M-3)."""
    a = (1.0 - level) / 2.0
    return float(chi2.ppf(a, dof)), float(chi2.ppf(1.0 - a, dof))
