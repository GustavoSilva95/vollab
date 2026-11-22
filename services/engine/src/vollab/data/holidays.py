"""Feriados da B3 (RN-PRC-05, QA-02, PRD §6.1).

Base: lista nacional 2001–2078 (`db/seed/feriados.csv`, formato ANBIMA `DD/MM/AAAA;;`),
complementada pelas regras da B3: 20/11 a partir de 2024, 24/12 e 31/12 sem pregão.
Os anos publicados pela B3 e conferidos na Etapa 0 (2025 e 2026) entram como `confirmed`.
Os demais ficam provisórios até a B3 publicar.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Literal

SEED_FILE = Path(__file__).resolve().parents[1] / "db" / "seed" / "feriados.csv"
FIRST_YEAR, LAST_YEAR = 2001, 2078
CONFIRMED_YEARS = frozenset({2025, 2026})

HolidaySource = Literal["b3_official", "national_list", "b3_rule"]


@dataclass(frozen=True, slots=True)
class Holiday:
    day: date
    source: HolidaySource
    confirmed: bool
    note: str | None = None


def parse_national_list(text: str) -> list[date]:
    days: list[date] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        raw = line.strip().split(";")[0].strip()
        if not raw or raw.lower() == "data":
            continue
        try:
            days.append(datetime.strptime(raw, "%d/%m/%Y").date())  # noqa: DTZ007 (só a data)
        except ValueError:
            raise ValueError(f"Linha {lineno} da lista de feriados com data inválida.") from None
    return days


def b3_rule_days(years: Iterable[int]) -> list[tuple[date, str]]:
    out: list[tuple[date, str]] = []
    for year in years:
        if year >= 2024:
            out.append((date(year, 11, 20), "Consciência Negra (sem pregão desde 2024)"))
        out.append((date(year, 12, 24), "Véspera de Natal (sem pregão)"))
        out.append((date(year, 12, 31), "Último dia do ano (sem pregão)"))
    return out


def build_holidays(national: Iterable[date]) -> list[Holiday]:
    by_day: dict[date, Holiday] = {}
    for day in national:
        by_day[day] = Holiday(day, "national_list", day.year in CONFIRMED_YEARS)
    for day, note in b3_rule_days(range(FIRST_YEAR, LAST_YEAR + 1)):
        if day not in by_day:
            by_day[day] = Holiday(day, "b3_rule", day.year in CONFIRMED_YEARS, note)
    return sorted(by_day.values(), key=lambda h: h.day)


def seed_holidays() -> list[Holiday]:
    return build_holidays(parse_national_list(SEED_FILE.read_text(encoding="utf-8")))
