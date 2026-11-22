from collections.abc import Iterator
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from tests.conftest import LOCAL
from vollab.api.app import create_app
from vollab.api.export_openapi import openapi_document, render
from vollab.db.session import get_session


class _BrokenSession:
    def execute(self, *args: Any, **kwargs: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def _client_with_broken_db() -> TestClient:
    app = create_app()

    def _session() -> Iterator[_BrokenSession]:
        yield _BrokenSession()

    app.dependency_overrides[get_session] = _session
    return TestClient(app, base_url=LOCAL)


def test_health_reports_degraded_when_database_is_down() -> None:
    response = _client_with_broken_db().get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"
    assert body["last_collection_at"] is None
    assert body["engine_version"]


def test_unknown_route_returns_problem_details() -> None:
    """PRD §7: erros seguem RFC 9457."""
    response = TestClient(create_app(), base_url=LOCAL).get("/nao-existe")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "Not Found",
        "instance": "/nao-existe",
    }


def test_validation_error_returns_problem_details() -> None:
    app = create_app()

    @app.get("/_teste/{n}")
    def _route(n: int) -> dict[str, int]:
        return {"n": n}

    response = TestClient(app, base_url=LOCAL).get("/_teste/abc")
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["status"] == 422
    assert body["errors"][0]["loc"] == ["path", "n"]


def test_no_cors_middleware() -> None:
    """ADR-09 / PRD-NF-01: mesma origem via rewrites; nenhum CORS aberto."""
    app = create_app()
    names = {m.cls.__name__ for m in app.user_middleware}  # type: ignore[attr-defined]
    assert "CORSMiddleware" not in names
    response = TestClient(app, base_url=LOCAL).get("/health", headers={"Origin": "https://exemplo.com"})
    assert "access-control-allow-origin" not in response.headers


def test_openapi_export_is_deterministic() -> None:
    """contract-drift depende de a exportação ser estável."""
    assert render() == render()


def test_openapi_contract_basics() -> None:
    doc = openapi_document()
    assert doc["paths"]["/health"]["get"]["operationId"] == "get_health"
    assert "ProblemDetails" in doc["components"]["schemas"]
    # A versão do contrato não pode ser o git sha (mudaria a cada commit).
    assert doc["info"]["version"] == "0.1.0"


def test_rejects_foreign_host_dns_rebinding() -> None:
    """PRD-NF-01: um domínio religado para 127.0.0.1 não consegue ler o engine."""
    client = TestClient(create_app(), base_url="http://evil.example:8000")
    response = client.get("/health")
    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"


def test_rejects_foreign_forwarded_host_via_next_rewrite() -> None:
    """O rewrite do Next troca o Host (changeOrigin) e repassa o original em X-Forwarded-Host."""
    client = TestClient(create_app(), base_url=LOCAL)
    assert client.get("/health", headers={"X-Forwarded-Host": "evil.example:3000"}).status_code == 400
    assert client.get("/health", headers={"X-Forwarded-Host": "localhost:3000"}).status_code == 200


def test_accepts_local_hosts() -> None:
    for host in ("http://localhost:8000", "http://127.0.0.1", "http://[::1]:8000"):
        assert TestClient(create_app(), base_url=host).get("/health").status_code == 200
