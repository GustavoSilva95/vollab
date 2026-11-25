"""Aplicação FastAPI do engine (ADR-03).

Sem CORS: o navegador fala com o engine pela mesma origem do Next (rewrites, ADR-09).
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from vollab.api.errors import install_error_handlers
from vollab.api.host_guard import HostGuardMiddleware
from vollab.api.routes import (
    alerts,
    collection,
    config,
    events,
    forecast,
    health,
    journal,
    portfolio,
    ranking,
    simulation,
    underlyings,
    vol,
)
from vollab.api.schemas.common import ProblemDetails
from vollab.settings import get_settings

# Versão do CONTRATO (OpenAPI). Não é o git sha: este valor entra no arquivo gerado e
# versionado, e mudar a cada commit faria o contract-drift falhar sem motivo.
API_VERSION = "0.8.0"


def _operation_id(route: APIRoute) -> str:
    # Gera nomes limpos no cliente (`get_health` → `getHealth`).
    return route.name


def create_app(*, allowed_hosts: list[str] | None = None) -> FastAPI:
    """`allowed_hosts` padrão vem de ALLOWED_HOSTS (Settings). Sem CORS (ADR-09)."""
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
    hosts = allowed_hosts if allowed_hosts is not None else get_settings().allowed_hosts
    app.add_middleware(HostGuardMiddleware, allowed_hosts=hosts)
    app.include_router(health.router)
    app.include_router(collection.router)
    app.include_router(underlyings.router)
    app.include_router(vol.router)
    app.include_router(events.router)
    app.include_router(forecast.router)
    app.include_router(ranking.router)
    app.include_router(config.router)
    app.include_router(simulation.router)
    app.include_router(journal.router)
    app.include_router(portfolio.router)
    app.include_router(alerts.router)
    return app
