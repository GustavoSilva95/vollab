"""Adaptador do COTAHIST da B3 (BRD §8, RN-DAD-01/02): layout fixo de 245 colunas.

Registros: `00` cabeçalho, `01` cotação, `99` trailer. Usamos:
- `TPMERC 010` (vista) para o OHLC oficial do ativo-objeto;
- `TPMERC 070/080` (opções de compra/venda) para o cadastro de séries e o pré-filtro.
Preços vêm com 2 casas implícitas. Os nomes de campo da B3 só existem nesta camada (ADR-16).
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from vollab.data.safe_zip import iter_member_lines

LINE_LENGTH = 245
# Diário ~4 MB; anual ~0,9 GB (2026). Limites com folga, conferidos durante a leitura.
MAX_DAILY_UNZIPPED_BYTES = 64_000_000
MAX_ANNUAL_UNZIPPED_BYTES = 2_500_000_000
MARKET_CASH = "010"
MARKET_CALL = "070"
MARKET_PUT = "080"
_WEEKLY = re.compile(r"W\d$")
_TICKER = re.compile(r"[A-Z0-9]{4,12}")


class CotahistParseError(ValueError):
    """Arquivo COTAHIST fora do layout esperado."""


@dataclass(frozen=True, slots=True)
class CotahistRecord:
    trade_date: date
    ticker: str
    market: str
    short_name: str
    specification: str
    open: Decimal
    high: Decimal
    low: Decimal
    avg: Decimal
    last: Decimal
    best_bid: Decimal
    best_ask: Decimal
    trades_count: int
    quantity: int
    volume: Decimal
    strike: Decimal
    expiry: date | None
    quote_factor: int
    isin: str

    @property
    def is_option(self) -> bool:
        return self.market in (MARKET_CALL, MARKET_PUT)

    @property
    def option_type(self) -> Literal["call", "put"]:
        return "call" if self.market == MARKET_CALL else "put"

    @property
    def is_weekly(self) -> bool:
        return bool(_WEEKLY.search(self.ticker))


def _yyyymmdd(raw: str) -> date:
    return date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))


def _price(raw: str) -> Decimal:
    return Decimal(int(raw)) / 100


def parse_record(line: str) -> CotahistRecord:
    if len(line) != LINE_LENGTH:
        raise CotahistParseError(f"Registro com {len(line)} colunas, esperado {LINE_LENGTH}.")
    try:
        expiry_raw = line[202:210]
        record = CotahistRecord(
            trade_date=_yyyymmdd(line[2:10]),
            ticker=line[12:24].strip(),
            market=line[24:27],
            short_name=line[27:39].strip(),
            specification=line[39:49].strip(),
            open=_price(line[56:69]),
            high=_price(line[69:82]),
            low=_price(line[82:95]),
            avg=_price(line[95:108]),
            last=_price(line[108:121]),
            best_bid=_price(line[121:134]),
            best_ask=_price(line[134:147]),
            trades_count=int(line[147:152]),
            quantity=int(line[152:170]),
            volume=_price(line[170:188]),
            strike=_price(line[188:201]),
            expiry=None if expiry_raw == "99991231" else _yyyymmdd(expiry_raw),
            quote_factor=int(line[210:217]),
            isin=line[230:242].strip(),
        )
    except ValueError:
        raise CotahistParseError("Registro com campo numérico ou data inválida.") from None
    if not _TICKER.fullmatch(record.ticker):
        raise CotahistParseError("Código de negociação inválido.")
    return record


@dataclass(frozen=True)
class CotahistFile:
    header_date: date
    records: list[CotahistRecord]


def parse_lines(
    lines: Iterable[bytes],
    *,
    keep: "RecordFilter",
) -> CotahistFile:
    """Lê as linhas do arquivo e devolve os registros aceitos por `keep`.

    Exige cabeçalho `00COTAHIST` e trailer `99COTAHIST` (detecta arquivo truncado).
    """
    header_date: date | None = None
    trailer = False
    records: list[CotahistRecord] = []
    for raw in lines:
        line = raw.decode("latin-1").rstrip("\r\n")
        if not line:
            continue
        if trailer:
            raise CotahistParseError("Conteúdo após o trailer.")
        kind = line[:2]
        if kind == "00":
            if header_date is not None or not line.startswith("00COTAHIST."):
                raise CotahistParseError("Cabeçalho do COTAHIST inválido.")
            try:
                header_date = _yyyymmdd(line[23:31])
            except ValueError:
                raise CotahistParseError("Data do cabeçalho inválida.") from None
        elif kind == "01":
            if header_date is None:
                raise CotahistParseError("Registro antes do cabeçalho.")
            # Filtro barato antes do parsing completo (o anual tem ~3,5 milhões de linhas).
            if keep.prefilter(line):
                records.append(parse_record(line))
        elif kind == "99":
            if not line.startswith("99COTAHIST."):
                raise CotahistParseError("Trailer do COTAHIST inválido.")
            trailer = True
        else:
            raise CotahistParseError("Tipo de registro desconhecido.")
    if header_date is None or not trailer:
        raise CotahistParseError("Arquivo COTAHIST incompleto (sem cabeçalho ou trailer).")
    return CotahistFile(header_date=header_date, records=records)


class RecordFilter:
    """Seleciona o que interessa: ações/ETFs do universo (vista) e opções sobre os ISINs dele."""

    def __init__(self, *, underlying_tickers: Iterable[str], underlying_isins: Iterable[str], options: bool):
        self.tickers = {t.upper() for t in underlying_tickers}
        self.isins = set(underlying_isins)
        self.options = options

    def prefilter(self, line: str) -> bool:
        market = line[24:27]
        if market == MARKET_CASH:
            return line[12:24].strip() in self.tickers
        if self.options and market in (MARKET_CALL, MARKET_PUT):
            return line[230:242] in self.isins
        return False


def read_cotahist(content: bytes, *, keep: RecordFilter, annual: bool) -> CotahistFile:
    limit = MAX_ANNUAL_UNZIPPED_BYTES if annual else MAX_DAILY_UNZIPPED_BYTES
    return parse_lines(iter_member_lines(content, max_bytes=limit), keep=keep)


def iter_options(records: Iterable[CotahistRecord]) -> Iterator[CotahistRecord]:
    return (r for r in records if r.is_option)


def infer_style(record: CotahistRecord) -> Literal["european", "american"]:
    """Estilo pelo sufixo `E` do nome resumido (RN-DAD-02; validado em 14.003/14.003 séries).

    A raiz é o prefixo de 4 letras do código (`PETR`, `VALE`): `PETRE` = europeia, `PETR` =
    americana. Comparar com a raiz evita confundir o `E` final de `VALE` com o marcador.
    """
    token = record.short_name.split()[0] if record.short_name else ""
    root = record.ticker[:4]
    return "european" if token == f"{root}E" else "american"
