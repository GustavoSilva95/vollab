"""Barras de 5 min do ativo-objeto e variância intradiária de um pregão (RN-VOL-08, PRD §5.5).

Puro, sem I/O. Entrada: negócios **já válidos pela R4** de um pregão (horário em segundos desde a
meia-noite de Brasília, identificador, preço e quantidade).

Regras (PRD §5.5 e Errata §2 da referência, eqs. 2.27/2.28):
- Grade fixa no relógio de Brasília a partir da abertura configurada (padrão 10:00), em barras de
  `bar_minutes`. O fim da sessão regular é a **hora cheia** do negócio de fechamento (o último pela
  ordem do identificador, que é o leilão de fechamento): 18:05 → 18:00. Assim a grade acompanha a
  mudança de horário da B3 (horário de verão nos EUA) sem configuração manual.
- Preço da barra = último negócio dentro dela (pela ordem do identificador, regra R4). Barra sem
  negócio repete o preço anterior e conta como vazia na cobertura.
- O 1º retorno parte da **abertura oficial** (nenhum retorno intradiário cobre a noite); o último
  termina no **fechamento oficial**. O retorno da noite entra à parte, na janela (RN-VOL-08).
- Pregão com cobertura abaixo do mínimo (padrão 80%) é **incompleto** e não entra na janela.
"""

import itertools
import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import ArrayLike, NDArray

SECONDS_PER_HOUR = 3600


@dataclass(frozen=True, slots=True)
class IntradaySession:
    session_open_s: int
    session_close_s: int
    bar_minutes: int
    bar_start_s: NDArray[np.int64]
    bar_price: NDArray[np.float64]
    bar_trades: NDArray[np.int64]
    bar_quantity: NDArray[np.int64]
    bars_with_trades: int
    coverage: float
    complete: bool
    # Σ ln(Pᵢ/Pᵢ₋₁)² de abertura oficial → barras → fechamento oficial, sem a noite (variância diária).
    intraday_variance: float
    trades_used: int

    @property
    def bars_total(self) -> int:
        return len(self.bar_start_s)


class IntradayError(ValueError):
    """Pregão sem dados suficientes para montar a grade."""


def session_close_from_closing_trade(closing_trade_s: float) -> int:
    """Hora cheia do negócio de fechamento (último pelo identificador)."""
    return int(closing_trade_s // SECONDS_PER_HOUR) * SECONDS_PER_HOUR


def build_session(
    time_s: ArrayLike,
    trade_id: ArrayLike,
    price: ArrayLike,
    quantity: ArrayLike,
    *,
    official_open: float,
    official_close: float,
    session_open_s: int = 10 * SECONDS_PER_HOUR,
    bar_minutes: int = 5,
    min_coverage: float = 0.8,
) -> IntradaySession:
    t = np.asarray(time_s, dtype=np.float64)
    ids = np.asarray(trade_id, dtype=np.int64)
    p = np.asarray(price, dtype=np.float64)
    q = np.asarray(quantity, dtype=np.int64)
    if t.size == 0:
        raise IntradayError("Pregão sem negócios válidos.")
    if not (official_open > 0 and official_close > 0):
        raise IntradayError("Abertura ou fechamento oficial inválido.")
    order = np.argsort(ids, kind="stable")
    t, ids, p, q = t[order], ids[order], p[order], q[order]
    close_s = session_close_from_closing_trade(float(t[-1]))
    step = bar_minutes * 60
    n_bars = (close_s - session_open_s) // step
    if n_bars < 1:
        raise IntradayError("Sessão regular menor que uma barra.")
    starts = session_open_s + step * np.arange(n_bars, dtype=np.int64)
    # Negócio antes da abertura vai para a 1ª barra; a partir do fim da sessão (leilão de
    # fechamento) fica fora das barras: o último retorno termina no fechamento oficial.
    in_session = t < close_s
    bar_idx = np.clip(((t[in_session] - session_open_s) // step).astype(np.int64), 0, n_bars - 1)
    p_in, q_in = p[in_session], q[in_session]
    trades_per_bar = np.bincount(bar_idx, minlength=n_bars).astype(np.int64)
    qty_per_bar = np.bincount(bar_idx, weights=q_in, minlength=n_bars).astype(np.int64)
    # Último pela ordem do identificador: como já está ordenado, o último índice de cada barra.
    last_price = np.full(n_bars, np.nan)
    last_price[bar_idx] = p_in  # atribuições posteriores sobrescrevem: fica o último
    filled = trades_per_bar > 0
    # Barra vazia repete o preço anterior (antes do 1º negócio: a abertura oficial).
    prices = np.empty(n_bars)
    prev = float(official_open)
    for i in range(n_bars):
        if filled[i]:
            prev = float(last_price[i])
        prices[i] = prev
    path = np.concatenate([[official_open], prices, [official_close]])
    rets = np.diff(np.log(path))
    bars_with = int(filled.sum())
    coverage = bars_with / n_bars
    return IntradaySession(
        session_open_s=session_open_s,
        session_close_s=close_s,
        bar_minutes=bar_minutes,
        bar_start_s=starts,
        bar_price=prices,
        bar_trades=trades_per_bar,
        bar_quantity=qty_per_bar,
        bars_with_trades=bars_with,
        coverage=coverage,
        complete=coverage >= min_coverage,
        intraday_variance=float(np.sum(rets * rets)),
        trades_used=int(t.size),
    )


def realized_variance_naive(path: list[float]) -> float:
    """Implementação ingênua (laço) para os testes de referência."""
    total = 0.0
    for a, b in itertools.pairwise(path):
        r = math.log(b / a)
        total += r * r
    return total
