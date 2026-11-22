"""Adaptador do Banco Central (SGS): Selic diária (RN-PRC-03).

Série 1178 = Selic anualizada base 252, em **percentual** (`"13.65"`). Convertemos para
decimal na ingestão (PRD §5.1): `13.65` → `0.1365`.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

SELIC_SERIES = 1178
MAX_BYTES = 5_000_000


class SgsParseError(ValueError):
    """Resposta do SGS fora do formato esperado."""


@dataclass(frozen=True, slots=True)
class RatePoint:
    day: date
    rate: Decimal  # decimal anual, base 252, capitalização exponencial


def parse_sgs(content: bytes) -> list[RatePoint]:
    if len(content) > MAX_BYTES:
        raise SgsParseError("Resposta do SGS acima do limite.")
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SgsParseError("Resposta do SGS não é JSON.") from None
    if not isinstance(payload, list):
        raise SgsParseError("Resposta do SGS não é uma lista.")
    points: dict[date, RatePoint] = {}
    for item in payload:
        if not isinstance(item, dict) or not isinstance(item.get("data"), str):
            raise SgsParseError("Item do SGS sem data.")
        raw_value = item.get("valor")
        if not isinstance(raw_value, str):
            raise SgsParseError("Item do SGS sem valor.")
        try:
            day = datetime.strptime(item["data"], "%d/%m/%Y").date()  # noqa: DTZ007 (só a data)
            percent = Decimal(raw_value)
        except (ValueError, InvalidOperation):
            raise SgsParseError("Data ou valor inválido no SGS.") from None
        if not percent.is_finite() or not Decimal(-5) < percent < Decimal(100):
            raise SgsParseError("Taxa fora do intervalo plausível.")
        points[day] = RatePoint(day=day, rate=percent / 100)
    return sorted(points.values(), key=lambda p: p.day)
