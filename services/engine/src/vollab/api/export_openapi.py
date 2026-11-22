"""Exporta o OpenAPI do engine de forma determinística (ADR-10).

Uso: `python -m vollab.api.export_openapi <arquivo-de-saída>`
A saída é a entrada do gerador em `packages/api-types` e o insumo do job `contract-drift`.
"""

import json
import sys
from pathlib import Path
from typing import Any

from vollab.api.app import create_app


def openapi_document() -> dict[str, Any]:
    # O guarda de Host não altera o schema; assim a exportação não exige DATABASE_URL.
    return create_app(allowed_hosts=[]).openapi()


def render() -> str:
    return json.dumps(openapi_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("uso: python -m vollab.api.export_openapi <saida.json>", file=sys.stderr)
        return 2
    Path(argv[1]).write_text(render(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
