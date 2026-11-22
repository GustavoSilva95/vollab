"""Erros no formato *problem details* (RFC 9457, PRD §7)."""

from http import HTTPStatus

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from vollab.api.schemas.common import ProblemDetails

PROBLEM_JSON = "application/problem+json"
log = structlog.get_logger("vollab.api.errors")


def _problem(request: Request, status: int, *, detail: str | None = None, **extra: object) -> JSONResponse:
    body = ProblemDetails(
        title=HTTPStatus(status).phrase,
        status=status,
        detail=detail,
        instance=request.url.path,
        **extra,
    )
    return JSONResponse(
        jsonable_encoder(body, exclude_none=True), status_code=status, media_type=PROBLEM_JSON
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else None
        return _problem(request, exc.status_code, detail=detail)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
            for err in exc.errors()
        ]
        return _problem(request, 422, detail="Dados inválidos.", errors=errors)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("api.unhandled_error", path=request.url.path)
        return _problem(request, 500, detail="Erro interno do engine.")
