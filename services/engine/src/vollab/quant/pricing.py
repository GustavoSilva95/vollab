"""Black-Scholes europeu com dividendos discretos e volatilidade implícita (RN-PRC-01, RF-VOL-02).

Puro: recebe números ou arrays e devolve números ou arrays, sem I/O (PRD §4).

Convenções (PRD §5.1, RN-PRC-04):
- `t` em anos úteis (dias úteis / 252); `sigma` decimal anualizado em base 252.
- `rate` é a taxa **contínua** equivalente: a Selic do SGS é exponencial em base 252, então
  `continuous_rate(selic) = ln(1 + selic)` e o desconto (1 + selic)^(−t) = e^(−rate·t).
- Dividendos discretos pelo modelo de dividendo descontado ("escrowed"): S* = S − VP(dividendos
  com data ex até o vencimento). Hull, *Options, Futures and Other Derivatives*, cap. 15.
- Greeks: delta e gamma por unidade do ativo; **vega por 1 ponto de vol (0,01)**; **theta por dia
  útil** (PRD §5.1). Fórmulas conforme a referência técnica (§3 Cap. 1 e §6, `bsm`).
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum

import numpy as np
from numpy.typing import ArrayLike, NDArray
from scipy.special import ndtr

BUSINESS_DAYS_PER_YEAR = 252
_SQRT_2PI = math.sqrt(2.0 * math.pi)

FloatArray = NDArray[np.float64]


def continuous_rate(rate_exponential: float) -> float:
    """Taxa anual exponencial em base 252 (decimal, ex.: Selic 0.1490) → taxa contínua."""
    if rate_exponential <= -1.0:
        raise ValueError("Taxa exponencial deve ser maior que −1.")
    return math.log1p(rate_exponential)


def years_from_business_days(days_bd: int) -> float:
    """Dias úteis → anos úteis (base 252)."""
    if days_bd < 0:
        raise ValueError("Prazo em dias úteis não pode ser negativo.")
    return days_bd / BUSINESS_DAYS_PER_YEAR


@dataclass(frozen=True, slots=True)
class Dividend:
    """Provento em dinheiro: prazo até a data ex (anos úteis) e valor por ação (BRL)."""

    t_ex: float
    amount: float


def pv_dividends(dividends: Iterable[Dividend], t: float, rate: float) -> float:
    """Valor presente dos proventos com data ex em (0, t]. Data ex hoje (t_ex = 0) já está no preço."""
    return sum(d.amount * math.exp(-rate * d.t_ex) for d in dividends if 0.0 < d.t_ex <= t)


def _norm_pdf(x: FloatArray) -> FloatArray:
    return np.exp(-0.5 * x * x) / _SQRT_2PI


def _as_array(x: ArrayLike) -> FloatArray:
    return np.asarray(x, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class BsResult:
    """Preço e Greeks nas unidades do PRD §5.1 (arrays com o formato das entradas)."""

    price: FloatArray
    delta: FloatArray
    gamma: FloatArray
    vega_per_point: FloatArray
    theta_per_bd: FloatArray


def bs_price(
    spot: ArrayLike,
    strike: ArrayLike,
    t: ArrayLike,
    rate: ArrayLike,
    sigma: ArrayLike,
    is_call: ArrayLike,
    pv_div: ArrayLike = 0.0,
) -> FloatArray:
    """Preço europeu com S* = S − VP(dividendos). Exige t > 0, sigma > 0 e S* > 0."""
    s_star = _as_array(spot) - _as_array(pv_div)
    k = _as_array(strike)
    tt = _as_array(t)
    r = _as_array(rate)
    vol = _as_array(sigma)
    call = np.asarray(is_call, dtype=bool)
    sq = vol * np.sqrt(tt)
    d1 = (np.log(s_star / k) + (r + 0.5 * vol * vol) * tt) / sq
    d2 = d1 - sq
    df = np.exp(-r * tt)
    call_price = s_star * ndtr(d1) - k * df * ndtr(d2)
    put_price = k * df * ndtr(-d2) - s_star * ndtr(-d1)
    return np.where(call, call_price, put_price)


def bs_greeks(
    spot: ArrayLike,
    strike: ArrayLike,
    t: ArrayLike,
    rate: ArrayLike,
    sigma: ArrayLike,
    is_call: ArrayLike,
    pv_div: ArrayLike = 0.0,
) -> BsResult:
    """Preço e Greeks. Com dividendos, o theta inclui a passagem do tempo até as datas ex:
    dS*/dτ = −rate·VP(div), logo theta = θ_BS(S*) − rate·VP(div)·delta (por ano, antes de /252)."""
    s_star = _as_array(spot) - _as_array(pv_div)
    pvd = _as_array(pv_div)
    k = _as_array(strike)
    tt = _as_array(t)
    r = _as_array(rate)
    vol = _as_array(sigma)
    call = np.asarray(is_call, dtype=bool)
    sqrt_t = np.sqrt(tt)
    sq = vol * sqrt_t
    d1 = (np.log(s_star / k) + (r + 0.5 * vol * vol) * tt) / sq
    d2 = d1 - sq
    df = np.exp(-r * tt)
    pdf1 = _norm_pdf(d1)
    price = np.where(
        call,
        s_star * ndtr(d1) - k * df * ndtr(d2),
        k * df * ndtr(-d2) - s_star * ndtr(-d1),
    )
    delta = np.where(call, ndtr(d1), ndtr(d1) - 1.0)
    gamma = pdf1 / (s_star * sq)
    vega = s_star * pdf1 * sqrt_t  # por 1,00 de vol
    theta_bs = np.where(
        call,
        -s_star * pdf1 * vol / (2.0 * sqrt_t) - r * k * df * ndtr(d2),
        -s_star * pdf1 * vol / (2.0 * sqrt_t) + r * k * df * ndtr(-d2),
    )
    theta_year = theta_bs - r * pvd * delta
    return BsResult(
        price=price,
        delta=delta,
        gamma=gamma,
        vega_per_point=vega / 100.0,
        theta_per_bd=theta_year / BUSINESS_DAYS_PER_YEAR,
    )


def bs_delta(
    spot: ArrayLike,
    strike: ArrayLike,
    t: ArrayLike,
    rate: ArrayLike,
    sigma: ArrayLike,
    is_call: ArrayLike,
    pv_div: ArrayLike = 0.0,
) -> FloatArray:
    """Só o delta (mesma fórmula de `bs_greeks`): o hedge da simulação não precisa dos outros Greeks
    (revisão de performance da Etapa 6, I-1: ~5,7× mais rápido por pregão)."""
    s_star = _as_array(spot) - _as_array(pv_div)
    tt = _as_array(t)
    vol = _as_array(sigma)
    d1 = (np.log(s_star / _as_array(strike)) + (_as_array(rate) + 0.5 * vol * vol) * tt) / (vol * np.sqrt(tt))
    n1 = ndtr(d1)
    return np.where(np.asarray(is_call, dtype=bool), n1, n1 - 1.0)


class IvStatus(IntEnum):
    """Resultado do cálculo da IV de cada negócio (T-REF-02: falha explícita, sem número)."""

    OK = 0
    BELOW_INTRINSIC = 1  # preço ≤ valor intrínseco descontado: não existe sigma > 0
    ABOVE_UPPER_BOUND = 2  # preço ≥ limite de arbitragem (S* da call, K·DF da put)
    NOT_CONVERGED = 3
    INVALID_INPUT = 4  # prazo ≤ 0, preço ≤ 0, S* ≤ 0 ou strike ≤ 0
    OUT_OF_RANGE = 5  # solução fora de [SIGMA_MIN, SIGMA_MAX]


SIGMA_MIN = 1e-4
SIGMA_MAX = 10.0


@dataclass(frozen=True, slots=True)
class IvResult:
    iv: FloatArray  # NaN onde status ≠ OK
    status: NDArray[np.int8]


def implied_vol(
    price: ArrayLike,
    spot: ArrayLike,
    strike: ArrayLike,
    t: ArrayLike,
    rate: ArrayLike,
    is_call: ArrayLike,
    pv_div: ArrayLike = 0.0,
    *,
    tol: float = 1e-12,
    max_iter: int = 100,
) -> IvResult:
    """IV vetorizada: Newton protegido por bisseção (o intervalo [lo, hi] sempre contém a raiz).

    O preço BS é estritamente crescente em sigma, então a raiz é única quando o preço está
    entre os limites de arbitragem; fora deles a IV não existe e o status diz por quê.
    """
    p, s, k, tt, r, call, pvd = np.broadcast_arrays(
        _as_array(price),
        _as_array(spot),
        _as_array(strike),
        _as_array(t),
        _as_array(rate),
        np.asarray(is_call, dtype=bool),
        _as_array(pv_div),
    )
    shape = p.shape
    p = p.astype(np.float64).ravel()
    s_star = (s - pvd).astype(np.float64).ravel()
    k = k.astype(np.float64).ravel()
    tt = tt.astype(np.float64).ravel()
    r = r.astype(np.float64).ravel()
    call = call.ravel()

    status = np.full(p.shape, IvStatus.OK, dtype=np.int8)
    valid = np.isfinite(p) & np.isfinite(s_star) & np.isfinite(k) & np.isfinite(tt) & np.isfinite(r)
    valid &= (p > 0) & (s_star > 0) & (k > 0) & (tt > 0)
    status[~valid] = IvStatus.INVALID_INPUT
    # Valores sem significado nas posições inválidas só para não gerar avisos de NaN.
    s_star = np.where(valid, s_star, 1.0)
    k = np.where(valid, k, 1.0)
    tt = np.where(valid, tt, 1.0)
    r = np.where(valid, r, 0.0)
    p = np.where(valid, p, 0.5)

    df = np.exp(-r * tt)
    lower = np.where(call, np.maximum(s_star - k * df, 0.0), np.maximum(k * df - s_star, 0.0))
    upper = np.where(call, s_star, k * df)
    below = valid & (p <= lower)
    above = valid & (p >= upper)
    status[below] = IvStatus.BELOW_INTRINSIC
    status[above] = IvStatus.ABOVE_UPPER_BOUND
    active = valid & ~below & ~above

    lo = np.full(p.shape, SIGMA_MIN)
    hi = np.full(p.shape, SIGMA_MAX)
    p_lo = bs_price(s_star, k, tt, r, lo, call)
    p_hi = bs_price(s_star, k, tt, r, hi, call)
    out_of_range = active & ((p < p_lo) | (p > p_hi))
    status[out_of_range] = IvStatus.OUT_OF_RANGE
    active &= ~out_of_range

    # Chute inicial: Manaster-Koehler, sqrt(2|ln(F/K)|/t), limitado ao intervalo.
    fwd = s_star / df
    guess = np.sqrt(np.abs(np.log(fwd / k)) * 2.0 / tt)
    sigma = np.clip(np.where(guess > 0.0, guess, 0.3), 0.05, 2.0)
    converged = ~active
    for _ in range(max_iter):
        todo = ~converged
        if not todo.any():
            break
        res = bs_greeks(s_star[todo], k[todo], tt[todo], r[todo], sigma[todo], call[todo])
        diff = res.price - p[todo]
        vega = res.vega_per_point * 100.0
        sig = sigma[todo]
        lo_t = np.where(diff < 0, sig, lo[todo])
        hi_t = np.where(diff > 0, sig, hi[todo])
        with np.errstate(divide="ignore", invalid="ignore"):
            newton = sig - diff / vega
        inside = np.isfinite(newton) & (newton >= lo_t) & (newton <= hi_t)
        new_sig = np.where(inside, newton, 0.5 * (lo_t + hi_t))
        # Convergência pelo preço: fica com o sigma que reprecifica (antes, o passo seguinte podia cair
        # na fronteira do intervalo, virar bisseção e devolver o ponto médio com status OK).
        priced = np.abs(diff) < tol * np.maximum(p[todo], 1e-300)
        new_sig = np.where(priced, sig, new_sig)
        done = priced | (np.abs(new_sig - sig) < tol) | ((hi_t - lo_t) < tol)
        lo[todo] = lo_t
        hi[todo] = hi_t
        sigma[todo] = new_sig
        idx = np.flatnonzero(todo)
        converged[idx[done]] = True
    not_conv = active & ~converged
    status[not_conv] = IvStatus.NOT_CONVERGED
    iv = np.where(status == IvStatus.OK, sigma, np.nan)
    return IvResult(iv=iv.reshape(shape), status=status.reshape(shape))
