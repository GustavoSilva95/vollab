"""Proteção contra DNS rebinding (PRD-NF-01).

Um site malicioso pode religar o próprio domínio para 127.0.0.1 e ler respostas "de mesma
origem". A defesa é recusar requisições cujo `Host` não seja local. Como o rewrite do Next
reescreve o `Host` para o destino (changeOrigin) e repassa o original em `X-Forwarded-Host`,
os dois cabeçalhos são verificados.
"""

from collections.abc import Iterable

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from vollab.api.errors import PROBLEM_JSON


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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or self._is_allowed(Headers(scope=scope)):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            {
                "type": "about:blank",
                "title": "Bad Request",
                "status": 400,
                "detail": "Host não permitido.",
                "instance": scope.get("path", ""),
            },
            status_code=400,
            media_type=PROBLEM_JSON,
        )
        await response(scope, receive, send)
