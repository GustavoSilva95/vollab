"""Fontes de dados isoladas atrás de uma interface única (RF-DAD-07, PRD §2 princípio 2).

`LiveSources` baixa das fontes reais; `FixtureSources` lê arquivos salvos (E2E, demonstração e
testes; nenhum teste de CI acessa a rede, PRD §10.4). Trocar uma fonte não toca as regras de
negócio: a coleta só conhece `MarketDataSources`.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol

from vollab.data.http import PoliteClient, SourceNotFoundError
from vollab.settings import Settings

_TICKER = re.compile(r"[A-Z0-9]{4,12}")

# Limites do corpo compactado (o descompactado é limitado no parsing).
MAX_TRADES_BYTES = 50_000_000
MAX_COTAHIST_DAILY_BYTES = 20_000_000
MAX_COTAHIST_ANNUAL_BYTES = 400_000_000
MAX_JSON_BYTES = 5_000_000


@dataclass(frozen=True)
class Fetched:
    http_status: int
    content: bytes
    content_format: str  # zip | json | csv


def _ticker(value: str) -> str:
    if not _TICKER.fullmatch(value):
        raise ValueError("Ticker inválido.")
    return value


def _guess_format(content: bytes, default: str) -> str:
    return "zip" if content[:4] == b"PK\x03\x04" else default


class MarketDataSources(Protocol):
    name: str

    def trades(self, ticker: str, day: date) -> Fetched: ...
    def cotahist_daily(self, day: date) -> Fetched: ...
    def cotahist_annual(self, year: int) -> Fetched: ...
    def selic(self, start: date, end: date) -> Fetched: ...
    def dividends(self, ticker: str) -> Fetched: ...
    def dividends_range(self, ticker: str, start: date, end: date) -> Fetched: ...
    def close(self) -> None: ...


class LiveSources:
    name = "live"

    def __init__(self, client: PoliteClient) -> None:
        self._client = client

    def trades(self, ticker: str, day: date) -> Fetched:
        url = f"https://drp.b3.com.br/rapinegocios/tickercsv/{_ticker(ticker)}/{day.isoformat()}?type=2"
        result = self._client.get(url, max_bytes=MAX_TRADES_BYTES)
        return Fetched(result.status, result.content, _guess_format(result.content, "csv"))

    def cotahist_daily(self, day: date) -> Fetched:
        url = f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{day:%d%m%Y}.ZIP"
        result = self._client.get(url, max_bytes=MAX_COTAHIST_DAILY_BYTES)
        return Fetched(result.status, result.content, "zip")

    def cotahist_annual(self, year: int) -> Fetched:
        url = f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_A{int(year):04d}.ZIP"
        result = self._client.get(url, max_bytes=MAX_COTAHIST_ANNUAL_BYTES)
        return Fetched(result.status, result.content, "zip")

    def selic(self, start: date, end: date) -> Fetched:
        url = (
            "https://api.bcb.gov.br/dados/serie/bcdata.sgs.1178/dados?formato=json"
            f"&dataInicial={start:%d/%m/%Y}&dataFinal={end:%d/%m/%Y}"
        )
        result = self._client.get(url, max_bytes=MAX_JSON_BYTES)
        return Fetched(result.status, result.content, "json")

    def dividends(self, ticker: str) -> Fetched:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{_ticker(ticker)}.SA"
            "?range=2y&interval=1d&events=div"
        )
        result = self._client.get(url, max_bytes=MAX_JSON_BYTES)
        return Fetched(result.status, result.content, "json")

    def dividends_range(self, ticker: str, start: date, end: date) -> Fetched:
        """Proventos de um período passado (cenário de crise, QA-12)."""
        p1 = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
        p2 = int(datetime(end.year, end.month, end.day, tzinfo=UTC).timestamp()) + 86_400
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{_ticker(ticker)}.SA"
            f"?period1={p1}&period2={p2}&interval=1d&events=div"
        )
        result = self._client.get(url, max_bytes=MAX_JSON_BYTES)
        return Fetched(result.status, result.content, "json")

    def close(self) -> None:
        self._client.close()


class FixtureSources:
    """Arquivos salvos com a mesma organização de `tests/fixtures/`. Ausente = HTTP 404."""

    name = "fixtures"

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _read(self, relative: str, content_format: str) -> Fetched:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise SourceNotFoundError("HTTP 404")
        content = path.read_bytes()
        return Fetched(200, content, _guess_format(content, content_format))

    def trades(self, ticker: str, day: date) -> Fetched:
        return self._read(f"b3/rapinegocios/{_ticker(ticker)}_{day.isoformat()}.zip", "csv")

    def cotahist_daily(self, day: date) -> Fetched:
        return self._read(f"b3/cotahist/COTAHIST_D{day:%d%m%Y}.ZIP", "zip")

    def cotahist_annual(self, year: int) -> Fetched:
        try:
            return self._read(f"b3/cotahist/COTAHIST_A{int(year):04d}.ZIP", "zip")
        except SourceNotFoundError:
            return self._read(f"b3/cotahist/COTAHIST_A{int(year):04d}_recorte.ZIP", "zip")

    def selic(self, start: date, end: date) -> Fetched:
        # O arquivo do mês final pedido (episódios de crise); senão, o mais recente (coleta).
        exact = self.root / "bcb" / f"sgs1178_{end:%Y-%m}.json"
        if exact.is_file():
            return self._read(f"bcb/sgs1178_{end:%Y-%m}.json", "json")
        files = sorted(f for f in (self.root / "bcb").glob("sgs1178_*.json") if f.name >= "sgs1178_2021")
        if not files:
            raise SourceNotFoundError("HTTP 404")
        return self._read(str(files[-1].relative_to(self.root)), "json")

    def dividends(self, ticker: str) -> Fetched:
        return self._read(f"yahoo/{_ticker(ticker)}.json", "json")

    def dividends_range(self, ticker: str, start: date, end: date) -> Fetched:
        return self._read(f"yahoo/{_ticker(ticker)}_{end:%Y}.json", "json")

    def close(self) -> None:
        return None


def build_sources(settings: Settings) -> MarketDataSources:
    if settings.data_source == "fixtures":
        if settings.fixtures_dir is None:  # o validador de Settings já impede
            raise ValueError("DATA_SOURCE=fixtures exige FIXTURES_DIR.")
        return FixtureSources(settings.fixtures_dir)
    client = PoliteClient(
        requests_per_second=settings.http_requests_per_second,
        timeout_s=settings.http_timeout_s,
        max_attempts=settings.http_max_attempts,
        backoff_base_s=settings.http_backoff_base_s,
        user_agent=settings.http_user_agent,
    )
    return LiveSources(client)
