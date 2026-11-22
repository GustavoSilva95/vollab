"""Cliente HTTP educado para as fontes externas (PRD-NF-02, RS-08).

- Ritmo máximo configurável (padrão 1 req/s), sequencial: sem paralelismo.
- Backoff exponencial em falhas transitórias (rede, 429, 5xx, 403 de bloqueio).
- `User-Agent` genérico; nenhum dado do usuário nas requisições.
- Só HTTPS e só os hosts das fontes conhecidas, inclusive em redirecionamentos.
- Corpo limitado durante o download (a resposta é entrada não confiável, PRD-NF-05).
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger("vollab.data.http")

ALLOWED_HOSTS = frozenset(
    {
        "drp.b3.com.br",
        "bvmf.bmfbovespa.com.br",
        "api.bcb.gov.br",
        "query1.finance.yahoo.com",
        "query2.finance.yahoo.com",
    }
)
# 403 entra como transitório: é a resposta típica de desafio anti-bot do Cloudflare (Etapa 0 §2).
TRANSIENT_STATUS = frozenset({403, 408, 425, 429, 500, 502, 503, 504})


class SourceNotFoundError(Exception):
    """HTTP 404: o recurso não existe (ex.: ticker inexistente). Não adianta tentar de novo."""


class TransientSourceError(Exception):
    """Falha que pode passar (rede, limite de ritmo, fonte fora do ar). Esgotou as tentativas."""


class SourceResponseError(Exception):
    """Resposta HTTP inesperada e não transitória (ex.: 400, 401)."""


@dataclass(frozen=True)
class HttpResult:
    status: int
    content: bytes


def _check_url(request: httpx.Request) -> None:
    if request.url.scheme != "https" or request.url.host not in ALLOWED_HOSTS:
        raise SourceResponseError("Destino fora da lista de fontes permitidas.")


class PoliteClient:
    def __init__(
        self,
        *,
        requests_per_second: float,
        timeout_s: float,
        max_attempts: int,
        backoff_base_s: float,
        user_agent: str,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = 1.0 / requests_per_second
        self._max_attempts = max_attempts
        self._backoff = backoff_base_s
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self._client = httpx.Client(
            timeout=timeout_s,
            follow_redirects=True,
            max_redirects=3,
            headers={"User-Agent": user_agent, "Accept": "*/*"},
            event_hooks={"request": [_check_url]},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _pace(self) -> None:
        if self._last is not None:
            wait = self._interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def _get_once(self, url: str, max_bytes: int) -> HttpResult:
        self._pace()
        with self._client.stream("GET", url) as response:
            if response.status_code == 404:
                raise SourceNotFoundError("HTTP 404")
            if response.status_code in TRANSIENT_STATUS:
                raise TransientSourceError(f"HTTP {response.status_code}")
            if response.status_code != 200:
                raise SourceResponseError(f"HTTP {response.status_code}")
            declared = response.headers.get("content-length")
            if declared is not None and declared.isdigit() and int(declared) > max_bytes:
                raise SourceResponseError("Resposta acima do limite de tamanho.")
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > max_bytes:
                    raise SourceResponseError("Resposta acima do limite de tamanho.")
            return HttpResult(response.status_code, bytes(body))

    def get(self, url: str, *, max_bytes: int) -> HttpResult:
        last_error = "falha desconhecida"
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._get_once(url, max_bytes)
            except TransientSourceError as exc:
                last_error = str(exc)
            except httpx.TransportError as exc:
                # Só o tipo do erro: a mensagem pode conter detalhes do ambiente (B-5).
                last_error = f"erro de rede ({type(exc).__name__})"
            except httpx.HTTPError as exc:
                # Laço de redirects, conteúdo comprimido inválido, URL inválida: não adianta repetir.
                raise SourceResponseError(f"resposta inválida ({type(exc).__name__})") from None
            if attempt < self._max_attempts:
                delay = self._backoff * (2 ** (attempt - 1))
                log.warning(
                    "http.retry", host=httpx.URL(url).host, attempt=attempt, delay_s=delay, error=last_error
                )
                self._sleep(delay)
        raise TransientSourceError(last_error)
