"""Adaptador do Yahoo Finance para o **histórico** de proventos (BRD §8, RS-02).

Usa a API de gráficos (`/v8/finance/chart/{T}.SA?events=div`), o mesmo backend do yfinance,
com httpx (decisão de 2026-11-22, PRD 1.3 §3.1). Limitações conhecidas (Etapa 0 §8): valores
podem divergir do ajuste oficial (bruto × líquido), sem tipo (dividendo × JCP) e sem proventos
futuros. Por isso tudo o que vem daqui é gravado como `estimated` e conferido com o ajuste de
strike do COTAHIST.
"""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MAX_BYTES = 5_000_000


class YahooParseError(ValueError):
    """Resposta do Yahoo fora do formato esperado."""


@dataclass(frozen=True, slots=True)
class DividendPoint:
    ex_date: date
    amount: Decimal  # BRL por ação, como informado pelo Yahoo


def parse_dividends(content: bytes, *, expected_symbol: str) -> list[DividendPoint]:
    if len(content) > MAX_BYTES:
        raise YahooParseError("Resposta do Yahoo acima do limite.")
    try:
        payload = json.loads(content)
        result = payload["chart"]["result"][0]
        symbol = result["meta"]["symbol"]
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError, IndexError, TypeError):
        raise YahooParseError("Resposta do Yahoo fora do formato esperado.") from None
    if symbol != f"{expected_symbol}.SA":
        raise YahooParseError("A resposta do Yahoo é de outro ativo.")
    events = result.get("events") or {}
    dividends = events.get("dividends") or {}
    if not isinstance(dividends, dict):
        raise YahooParseError("Bloco de dividendos inválido.")
    points: dict[date, DividendPoint] = {}
    for item in dividends.values():
        try:
            ts = int(item["date"])
            amount = Decimal(str(item["amount"]))
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise YahooParseError("Dividendo com data ou valor inválido.") from None
        if not amount.is_finite() or amount <= 0 or amount > 1000:
            raise YahooParseError("Valor de dividendo fora do intervalo plausível.")
        ex_date = datetime.fromtimestamp(ts, tz=UTC).astimezone(SAO_PAULO).date()
        # Mais de um valor na mesma data (raro): soma, como faz o próprio Yahoo no ajuste.
        previous = points.get(ex_date)
        total = amount + (previous.amount if previous else Decimal(0))
        points[ex_date] = DividendPoint(ex_date=ex_date, amount=total.quantize(Decimal("0.000001")))
    return sorted(points.values(), key=lambda p: p.ex_date)
