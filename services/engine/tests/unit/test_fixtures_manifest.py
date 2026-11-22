"""As fixtures reais da Etapa 0 conferem com o MANIFEST (SHA-256). Base dos testes de ingestão (Etapa 2)."""

import csv
import hashlib
from pathlib import Path

import vollab
from tests.conftest import FIXTURES

# A lista de feriados não é fixture de teste: foi para o seed de exchange_holidays (PLANO, Etapa 1).
SEED_DIR = Path(vollab.__file__).parent / "db" / "seed"


def _resolve(entry: str) -> Path:
    if entry.startswith("calendario/"):
        return SEED_DIR / Path(entry).name
    return FIXTURES / entry


def test_fixtures_match_manifest() -> None:
    with (FIXTURES / "MANIFEST.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) >= 50
    for row in rows:
        data = _resolve(row["arquivo"]).read_bytes()
        assert len(data) == int(row["bytes"]), row["arquivo"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"], row["arquivo"]
