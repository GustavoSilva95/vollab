"""Proteção contra DNS rebinding (PRD-NF-01).

Um site malicioso pode religar o próprio domínio para 127.0.0.1 e ler respostas "de mesma
origem". A defesa é recusar requisições cujo `Host` não seja local. Como o rewrite do Next
reescreve o `Host` para o destino (changeOrigin) e repassa o original em `X-Forwarded-Host`,
os dois cabeçalhos são verificados.

CSRF (revisão de segurança da Etapa 2, M-3): uma página qualquer pode mandar um POST para
127.0.0.1 (form ou `fetch` no-cors) e, por exemplo, disparar horas de downloads da B3. Em
métodos que alteram estado, recusamos `Origin` não local e `Sec-Fetch-Site: cross-site`.
"""

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from vollab.api.errors import PROBLEM_JSON

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _hostname(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):  # IPv6 com porta: [::1]:8000
        return value.split("]", 1)[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


class HostGuardMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        self.app = app
        self.allowed = {h.lower() for h in allowed_hosts}

    def _is_allowed(self, headers: Headers) -> bool:
        host = headers.get("host", "")
        if _hostname(host) not in self.allowed:
            return False
        # Pode vir uma lista separada por vírgulas se houver mais de um proxy.
        return all(
            _hostname(fwd) in self.allowed for fwd in headers.get("x-forwarded-host", "").split(",") if fwd
        )

    def _is_cross_site_write(self, method: str, headers: Headers) -> bool:
        if method in SAFE_METHODS:
            return False
        if headers.get("sec-fetch-site", "").lower() == "cross-site":
            return True
        origin = headers.get("origin")
        if origin is None:
            return False  # clientes que não são navegador (curl, testes) não mandam Origin
        if origin == "null":
            return True
        return _hostname(urlsplit(origin).netloc) not in self.allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        if not self._is_allowed(headers):
            status, title, detail = 400, "Bad Request", "Host não permitido."
        elif self._is_cross_site_write(scope.get("method", "GET"), headers):
            status, title, detail = 403, "Forbidden", "Requisição de outra origem recusada."
        else:
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {
                "type": "about:blank",
                "title": title,
                "status": status,
                "detail": detail,
                "instance": scope.get("path", ""),
            },
            status_code=status,
            media_type=PROBLEM_JSON,
        )
        await response(scope, receive, send)
