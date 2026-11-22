"""Ingestão com fixtures reais da B3 (PRD §10.1): parsing, R4 contra o OHLC oficial, cadastro."""

import csv
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tests.conftest import FIXTURES
from vollab.data.b3_cotahist import (
    CotahistParseError,
    CotahistRecord,
    RecordFilter,
    infer_style,
    parse_lines,
    read_cotahist,
)
from vollab.data.b3_trades import (
    TradesParseError,
    parse_trades,
    r4_filter,
    reconstruct_ohlc,
)

TRADES = FIXTURES / "b3" / "rapinegocios"
COTAHIST = FIXTURES / "b3" / "cotahist"
UNIVERSE_ISINS = {"BRPETRACNPR6", "BRBBASACNOR3", "BRBOVACTF003", "BRVALEACNOR0"}
UNIVERSE = {"PETR4", "BBAS3", "BOVA11", "VALE3"}


def _trades(path: Path) -> list:  # type: ignore[type-arg]
    ticker, day = path.stem.rsplit("_", 1)
    return parse_trades(path.read_bytes(), expected_instrument=ticker, expected_date=date.fromisoformat(day))


def _official() -> dict[tuple[str, date], CotahistRecord]:
    keep = RecordFilter(underlying_tickers=UNIVERSE, underlying_isins=UNIVERSE_ISINS, options=True)
    out: dict[tuple[str, date], CotahistRecord] = {}
    files = [(p, False) for p in sorted(COTAHIST.glob("COTAHIST_D*.ZIP"))]
    files.append((COTAHIST / "COTAHIST_A2026_recorte.ZIP", True))
    for path, annual in files:
        for rec in read_cotahist(path.read_bytes(), keep=keep, annual=annual).records:
            out[(rec.ticker, rec.trade_date)] = rec
    return out


def test_parse_types_and_time_without_leading_zero() -> None:
    rows = _trades(TRADES / "PETRL44_2026-11-19.zip")
    first = rows[0]
    # Negócio do pregão anterior, de madrugada (Etapa 0 §2): HoraFechamento 022944967.
    assert first.trade_date == date(2026, 11, 18)
    assert first.reference_date == date(2026, 11, 19)
    assert first.traded_at.isoformat() == "2026-11-18T02:29:44.967000-03:00"
    assert first.price == Decimal("1.650")
    assert first.quantity == 800


def test_holiday_file_with_only_header_is_empty() -> None:
    """RF-DAD-03: ZIP só com cabeçalho = pregão sem negócios (`vazio`, não `falha`)."""
    assert _trades(TRADES / "PETR4_2026-11-20.zip") == []


def test_cancellation_of_2026_11_06_uses_id_order() -> None:
    """QA-13: negócios cancelados e reemitidos em 06/11 (IDs 692280/692290)."""
    rows = _trades(TRADES / "PETR4_2026-11-06.zip")
    cancelled = {r.trade_id for r in rows if r.update_action != 0}
    assert {692280, 692290} <= cancelled
    valid = r4_filter(rows)
    ids = [r.trade_id for r in valid]
    assert 692280 not in ids and 692290 not in ids
    assert {692281, 692291} <= set(ids)
    assert ids == sorted(ids)
    ohlc = reconstruct_ohlc(valid)
    assert ohlc is not None
    assert ohlc.close == Decimal("45.36")  # ordenar por horário daria 45,30


def test_r4_matches_official_ohlc_in_all_fixture_pairs() -> None:
    """RN-DAD-01 / PRD §9 M1: a R4 reproduz o COTAHIST oficial em todos os pares das fixtures.

    A Etapa 0 conferiu 33 pares; com o recorte do anual 2026 são 41 (todas as fixtures menos o feriado).
    """
    official = _official()
    checked = 0
    for path in sorted(TRADES.glob("*.zip")):
        ticker, day = path.stem.rsplit("_", 1)
        ref = official.get((ticker, date.fromisoformat(day)))
        rows = _trades(path)
        if ref is None:
            assert rows == [], path.name  # 20/11: feriado
            continue
        ohlc = reconstruct_ohlc(r4_filter(rows))
        assert ohlc is not None, path.name
        assert (ohlc.trades_count, ohlc.open, ohlc.high, ohlc.low, ohlc.close) == (
            ref.trades_count,
            ref.open,
            ref.high,
            ref.low,
            ref.last,
        ), path.name
        assert abs(ohlc.vwap - ref.avg) <= Decimal("0.01"), path.name
        if (ticker, day) != ("PETR4", "2026-11-06"):
            assert ohlc.quantity == ref.quantity, path.name
        checked += 1
    assert checked == 41


def test_r4_excludes_previous_day_and_non_regular_session() -> None:
    rows = _trades(TRADES / "PETR4_2026-11-19.zip")
    valid = r4_filter(rows)
    assert any(r.session_type == 6 for r in rows)
    assert all(r.session_type == 1 and r.trade_date == r.reference_date for r in valid)


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"DataReferencia;Outro\n",
        b"DataReferencia;CodigoInstrumento;AcaoAtualizacao;PrecoNegocio;QuantidadeNegociada;HoraFechamento;"
        b"CodigoIdentificadorNegocio;TipoSessaoPregao;DataNegocio;CodigoParticipanteComprador;"
        b"CodigoParticipanteVendedor\n2026-11-19;PETR4;0;abc;100;100000000;1;1;2026-11-19;1;2\n",
    ],
)
def test_malformed_trades_are_rejected(content: bytes) -> None:
    with pytest.raises(TradesParseError):
        parse_trades(content, expected_instrument="PETR4", expected_date=date(2026, 11, 19))


def test_trades_for_another_ticker_are_rejected() -> None:
    content = (TRADES / "PETRL44_2026-11-19.zip").read_bytes()
    with pytest.raises(TradesParseError):
        parse_trades(content, expected_instrument="PETR4", expected_date=date(2026, 11, 19))


def test_direct_csv_is_accepted() -> None:
    """RF-DAD-03: CSV direto ou ZIP."""
    header = (
        "DataReferencia;CodigoInstrumento;AcaoAtualizacao;PrecoNegocio;QuantidadeNegociada;HoraFechamento;"
        "CodigoIdentificadorNegocio;TipoSessaoPregao;DataNegocio;CodigoParticipanteComprador;"
        "CodigoParticipanteVendedor"
    )
    body = f"{header}\n2026-11-19;PETR4;0;42,5;100;100000123;10;1;2026-11-19;;\n".encode()
    (row,) = parse_trades(body, expected_instrument="PETR4", expected_date=date(2026, 11, 19))
    assert row.traded_at == datetime.fromisoformat("2026-11-19T10:00:00.123-03:00")
    assert row.buyer is None


def test_cotahist_daily_header_and_underlyings() -> None:
    keep = RecordFilter(underlying_tickers=UNIVERSE, underlying_isins=UNIVERSE_ISINS, options=False)
    parsed = read_cotahist((COTAHIST / "COTAHIST_D19112026.ZIP").read_bytes(), keep=keep, annual=False)
    assert parsed.header_date == date(2026, 11, 19)
    by_ticker = {r.ticker: r for r in parsed.records}
    assert set(by_ticker) == UNIVERSE
    petr = by_ticker["PETR4"]
    assert (petr.open, petr.last, petr.isin) == (Decimal("43.53"), Decimal("42.67"), "BRPETRACNPR6")


def test_cotahist_options_carry_underlying_isin_and_style() -> None:
    keep = RecordFilter(underlying_tickers=(), underlying_isins={"BRPETRACNPR6"}, options=True)
    parsed = read_cotahist((COTAHIST / "COTAHIST_D19112026.ZIP").read_bytes(), keep=keep, annual=False)
    series = {r.ticker: r for r in parsed.records}
    assert all(r.isin == "BRPETRACNPR6" for r in parsed.records)
    l44 = series["PETRL44"]
    assert (l44.option_type, l44.strike, l44.expiry) == ("call", Decimal("43.16"), date(2026, 12, 18))
    assert infer_style(l44) == "european"
    # O prefixo PETR mistura PETR3 e PETR4: o filtro é pelo ISIN, nunca pelo ticker (RN-DAD-02).
    assert all(r.isin != "BRPETRACNOR9" for r in parsed.records)


def test_style_inference_matches_official_registry_for_universe() -> None:
    """RN-DAD-02: sufixo E ⇔ EURO (Cadastro de Instrumentos oficial, recorte de 19/11/2026)."""
    registry: dict[str, str] = {}
    registry_file = FIXTURES / "b3/instrumentos/InstrumentsConsolidated_2026-11-19_BOVA11-BBAS3-PETR4.csv"
    with registry_file.open(encoding="utf-8-sig") as fh:
        lines = fh.read().splitlines()[3:]
    for row in csv.DictReader(lines, delimiter=";"):
        if row["Estilo de opção"] in ("EURO", "AMER"):
            registry[row["Instrumento financeiro"]] = row["Estilo de opção"]
    keep = RecordFilter(
        underlying_tickers=(), underlying_isins={"BRPETRACNPR6", "BRBBASACNOR3", "BRBOVACTF003"}, options=True
    )
    parsed = read_cotahist((COTAHIST / "COTAHIST_D19112026.ZIP").read_bytes(), keep=keep, annual=False)
    assert len(parsed.records) == 2307
    for rec in parsed.records:
        expected = "european" if registry[rec.ticker] == "EURO" else "american"
        assert infer_style(rec) == expected, rec.ticker


def test_cotahist_truncated_file_is_rejected() -> None:
    header = b"00COTAHIST.2026BOVESPA 20261119".ljust(245) + b"\r\n"
    keep = RecordFilter(underlying_tickers=UNIVERSE, underlying_isins=(), options=False)
    with pytest.raises(CotahistParseError):
        parse_lines([header], keep=keep)
    with pytest.raises(CotahistParseError):
        parse_lines([b"01" + b"x" * 243 + b"\r\n"], keep=keep)


def test_annual_cut_has_full_year_of_underlying_bars() -> None:
    keep = RecordFilter(underlying_tickers=UNIVERSE, underlying_isins=(), options=False)
    parsed = read_cotahist((COTAHIST / "COTAHIST_A2026_recorte.ZIP").read_bytes(), keep=keep, annual=True)
    petr = [r for r in parsed.records if r.ticker == "PETR4"]
    assert len(petr) == 221
    days = sorted(r.trade_date for r in petr)
    assert (days[0], days[-1]) == (date(2026, 1, 2), date(2026, 11, 19))


def test_previous_day_trade_with_same_id_is_not_counted() -> None:
    """IDs reiniciam a cada pregão: o negócio de D-1 com ID 353710 não pode anular nem duplicar o do dia."""
    rows = _trades(TRADES / "PETR4_2026-11-18.zip")
    same_id = [r for r in rows if r.trade_id == 353710]
    assert {r.trade_date for r in same_id} == {date(2026, 11, 17), date(2026, 11, 18)}
    valid = [r for r in r4_filter(rows) if r.trade_id == 353710]
    assert [r.trade_date for r in valid] == [date(2026, 11, 18)]
