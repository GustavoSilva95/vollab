"""Aplicação FastAPI do engine (ADR-03).

Sem CORS: o navegador fala com o engine pela mesma origem do Next (rewrites, ADR-09).
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from vollab.api.errors import install_error_handlers
from vollab.api.routes import health
from vollab.api.schemas.common import ProblemDetails

# Versão do CONTRATO (OpenAPI). Não é o git sha: este valor entra no arquivo gerado e
# versionado, e mudar a cada commit faria o contract-drift falhar sem motivo.
API_VERSION = "0.1.0"


def _operation_id(route: APIRoute) -> str:
    # Gera nomes limpos no cliente (`get_health` → `getHealth`).
    return route.name


def create_app() -> FastAPI:
    app = FastAPI(
        title="VolLab Engine",
        version=API_VERSION,
        description=(
            "API do engine do VolLab. Unidades conforme PRD §5.1; estimativas em EstimatedValue (§5.2)."
        ),
        generate_unique_id_function=_operation_id,
        responses={"default": {"model": ProblemDetails, "description": "Erro (RFC 9457)"}},
    )
    install_error_handlers(app)
    app.include_router(health.router)
    return app


app = create_app()
