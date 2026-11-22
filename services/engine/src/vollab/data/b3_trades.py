"""Adaptador de parsing dos negócios da B3 (`rapinegocios`) e regra R4 (RF-DAD-03, RN-DAD-01).

Formato (Etapa 0, §2): CSV ou ZIP com um único `.txt`; separador `;`; decimal com vírgula;
`HoraFechamento` = `HHMMSSmmm` no horário de Brasília, sem zero à esquerda. ZIP só com o
cabeçalho = pregão sem negócios. Os nomes de campo da B3 só existem nesta camada (ADR-16).
"""

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from vollab.data.safe_zip import is_zip, read_single_member

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
HEADER = (
    "DataReferencia",
    "CodigoInstrumento",
    "AcaoAtualizacao",
    "PrecoNegocio",
    "QuantidadeNegociada",
    "HoraFechamento",
    "CodigoIdentificadorNegocio",
    "TipoSessaoPregao",
    "DataNegocio",
    "CodigoParticipanteComprador",
    "CodigoParticipanteVendedor",
)
# Um dia de PETR4 tem ~3 MB de texto; 100 MB cobre folga sem abrir espaço para abuso.
MAX_UNZIPPED_BYTES = 100_000_000
MAX_ROWS = 1_000_000
REGULAR_SESSION = 1
NEW_TRADE = 0


class TradesParseError(ValueError):
    """Arquivo de negócios fora do formato esperado."""


@dataclass(frozen=True, slots=True)
class TradeRow:
    reference_date: date
    instrument: str
    update_action: int
    price: Decimal
    quantity: int
    traded_at: datetime  # timestamptz em America/Sao_Paulo (PRD §5.1)
    trade_id: int
    session_type: int
    trade_date: date
    buyer: int | None
    seller: int | None


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _time(value: str) -> time:
    if not value.isdigit() or len(value) > 9:
        raise ValueError("HoraFechamento inválida")
    raw = value.zfill(9)
    return time(int(raw[0:2]), int(raw[2:4]), int(raw[4:6]), int(raw[6:9]) * 1000)


def _price(value: str) -> Decimal:
    price = Decimal(value.replace(",", "."))
    if not price.is_finite() or price < 0:
        raise ValueError("PrecoNegocio inválido")
    return price


def _optional_int(value: str) -> int | None:
    return int(value) if value.strip() else None


def decode_payload(content: bytes) -> str:
    """Aceita ZIP com um único arquivo ou CSV direto (RF-DAD-03)."""
    if is_zip(content):
        _, content = read_single_member(content, max_bytes=MAX_UNZIPPED_BYTES)
    elif len(content) > MAX_UNZIPPED_BYTES:
        raise TradesParseError("CSV acima do limite de tamanho.")
    # A B3 envia ASCII; latin-1 nunca falha e não aceita nada além de bytes simples.
    return content.decode("latin-1").lstrip("﻿")


def parse_trades(content: bytes, *, expected_instrument: str, expected_date: date) -> list[TradeRow]:
    """Lê o arquivo e valida cabeçalho, tipos e coerência com o ticker e a data consultados."""
    try:
        return _parse_rows(decode_payload(content), expected_instrument, expected_date)
    except csv.Error:
        raise TradesParseError("CSV malformado.") from None


def _parse_rows(text: str, expected_instrument: str, expected_date: date) -> list[TradeRow]:
    reader = csv.reader(io.StringIO(text), delimiter=";")
    header = next(reader, None)
    if header is None or tuple(h.strip() for h in header) != HEADER:
        raise TradesParseError("Cabeçalho inesperado no arquivo de negócios.")
    rows: list[TradeRow] = []
    for lineno, fields in enumerate(reader, start=2):
        if not fields or all(not f.strip() for f in fields):
            continue
        if len(fields) != len(HEADER):
            raise TradesParseError(f"Linha {lineno}: {len(fields)} campos, esperado {len(HEADER)}.")
        try:
            ref = _date(fields[0])
            traded_on = _date(fields[8])
            row = TradeRow(
                reference_date=ref,
                instrument=fields[1].strip(),
                update_action=int(fields[2]),
                price=_price(fields[3]),
                quantity=int(fields[4]),
                traded_at=datetime.combine(traded_on, _time(fields[5].strip()), tzinfo=SAO_PAULO),
                trade_id=int(fields[6]),
                session_type=int(fields[7]),
                trade_date=traded_on,
                buyer=_optional_int(fields[9]),
                seller=_optional_int(fields[10]),
            )
        except (ValueError, InvalidOperation, OverflowError):
            raise TradesParseError(f"Linha {lineno}: valor inválido.") from None
        if row.instrument != expected_instrument or row.reference_date != expected_date:
            raise TradesParseError(f"Linha {lineno}: instrumento ou data diferente do consultado.")
        if row.quantity < 0 or row.trade_id < 0:
            raise TradesParseError(f"Linha {lineno}: quantidade ou identificador negativo.")
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise TradesParseError("Número de linhas acima do limite.")
    return rows


def r4_mask(rows: Sequence[TradeRow]) -> list[bool]:
    """Regra R4 (RN-DAD-01): para cada linha, se o negócio é válido.

    1. só `DataNegocio = DataReferencia` e `TipoSessaoPregao = 1`;
    2. remove todo `CodigoIdentificadorNegocio` com alguma linha `AcaoAtualizacao ≠ 0`,
       inclusive a própria linha de cancelamento;
    3. a ordem é dada pelo identificador (ver `r4_filter`).

    A B3 reinicia os identificadores a cada pregão: o negócio de D-1 reapresentado pode ter o
    mesmo ID de um negócio do dia (PETR4, 18/11/2026, ID 353710). Por isso a identidade de um
    negócio é (DataNegocio, ID), nunca só o ID.
    """
    cancelled = {(r.trade_date, r.trade_id) for r in rows if r.update_action != NEW_TRADE}
    return [
        r.trade_date == r.reference_date
        and r.session_type == REGULAR_SESSION
        and r.update_action == NEW_TRADE
        and (r.trade_date, r.trade_id) not in cancelled
        for r in rows
    ]


def r4_filter(rows: Sequence[TradeRow]) -> list[TradeRow]:
    """Negócios válidos pela R4, ordenados pelo identificador (não pelo horário)."""
    valid = [r for r, ok in zip(rows, r4_mask(rows), strict=True) if ok]
    return sorted(valid, key=lambda r: r.trade_id)


@dataclass(frozen=True, slots=True)
class Ohlc:
    trades_count: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    quantity: int
    volume: Decimal

    @property
    def vwap(self) -> Decimal:
        return self.volume / self.quantity


def reconstruct_ohlc(valid_sorted: Sequence[TradeRow]) -> Ohlc | None:
    """OHLC a partir dos negócios já filtrados e ordenados pela R4."""
    if not valid_sorted:
        return None
    prices = [r.price for r in valid_sorted]
    return Ohlc(
        trades_count=len(valid_sorted),
        open=prices[0],
        high=max(prices),
        low=min(prices),
        close=prices[-1],
        quantity=sum(r.quantity for r in valid_sorted),
        volume=sum((r.price * r.quantity for r in valid_sorted), Decimal(0)),
    )
