"""Dimensionamento: Kelly fracionado e teto de perda (PRD 1.9 §5.8; BRD 1.6 RN-SIZ-01..05, QA-09).

Puro, sem I/O. Dinheiro em BRL; o resultado é um número **inteiro de lotes**.

- Kelly (eq. 8.14 da referência): maximizar E[ln(W + n·X)] para n lotes dá, para edge pequeno,
  n* = W·μ/σ², com μ = P&L esperado por lote no **limite inferior do edge** (já líquido de custos) e
  σ² = variância da **distribuição simulada** por lote (com as caudas do histórico; nunca a eq. 7.7).
  n_Kelly = ⌊f·W·μ/σ²⌋, f = fração de Kelly (padrão 1/4).
- Teto: n_teto = ⌊c·W/L⌋, L = perda máxima por lote = max(ES 99%, pior stress) (QA-09).
- Tamanho = min(n_Kelly, n_teto), com a regra que prevaleceu (RN-SIZ-04).

Os pisos são calculados em aritmética racional exata sobre o valor decimal de cada float (a menor
representação que o reproduz, `repr`), para o resultado não depender de arredondamento binário nas
fronteiras: em float, 0,29 × 100 = 28,999999999999996 (T-REF-07: igualdade exata).
"""

import math
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction


class Rule(StrEnum):
    KELLY = "kelly"  # o Kelly fracionado foi menor
    CAP = "cap"  # o teto foi menor
    TIE = "tie"  # iguais
    ZERO = "zero"  # sem tamanho positivo (RN-SIZ-05), com o motivo


@dataclass(frozen=True, slots=True)
class SizingInput:
    capital: float  # W, BRL
    kelly_fraction: float  # f
    max_loss_fraction: float  # c
    mu: float | None  # μ por lote, BRL (None: sem edge calculável)
    variance: float | None  # σ² por lote, BRL²
    max_loss: float | None  # L por lote, BRL
    edge_ok: bool  # semáforo em "edge líquido" na direção da estrutura
    zero_reason: str | None = None  # motivo quando edge_ok é falso


@dataclass(frozen=True, slots=True)
class Sizing:
    n_kelly: int
    n_cap: int | None  # None: nenhuma perda nos cenários (sem teto aplicável)
    n_final: int
    rule: Rule
    reason: str | None
    kelly_full: float | None  # W·μ/σ² (lotes, antes da fração e do piso), para exibição


def _q(x: float) -> Fraction:
    return Fraction(repr(float(x)))


def _floor(x: Fraction) -> int:
    return max(0, math.floor(x))


def size_position(inp: SizingInput) -> Sizing:
    if not (inp.capital > 0 and 0 < inp.kelly_fraction <= 1 and 0 < inp.max_loss_fraction <= 1):
        raise ValueError("size_position: capital positivo; frações em (0, 1].")
    w = _q(inp.capital)

    n_cap: int | None = None
    if inp.max_loss is not None and inp.max_loss > 0:
        n_cap = _floor(_q(inp.max_loss_fraction) * w / _q(inp.max_loss))

    reason: str | None = None
    kelly_full: float | None = None
    if not inp.edge_ok:
        reason = inp.zero_reason or 'semáforo fora de "edge líquido" na direção da estrutura'
    elif inp.mu is None or inp.variance is None:
        reason = "sem P&L esperado ou distribuição simulada"
    elif inp.mu <= 0:
        reason = "P&L esperado no limite inferior do edge não é positivo"
    elif inp.variance <= 0:
        reason = "distribuição simulada sem variância"
    if reason is not None or inp.mu is None or inp.variance is None:
        return Sizing(0, n_cap, 0, Rule.ZERO, reason, None)

    full = w * _q(inp.mu) / _q(inp.variance)
    kelly_full = float(full)
    n_kelly = _floor(_q(inp.kelly_fraction) * full)
    if n_cap is None or n_kelly < n_cap:
        n_final, rule = n_kelly, Rule.KELLY
    elif n_cap < n_kelly:
        n_final, rule = n_cap, Rule.CAP
    else:
        n_final, rule = n_kelly, Rule.TIE
    if n_final == 0:
        why = (
            "o Kelly fracionado não chega a 1 lote"
            if rule is Rule.KELLY
            else "o teto de perda não permite nem 1 lote"
        )
        return Sizing(n_kelly, n_cap, 0, rule, why, kelly_full)
    return Sizing(n_kelly, n_cap, n_final, rule, None, kelly_full)
