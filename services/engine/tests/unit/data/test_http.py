"""PRD-NF-02 (coleta educada) e PRD-NF-05 (resposta não confiável), sem rede: MockTransport."""

import httpx
import pytest

from vollab.data.http import PoliteClient, SourceNotFoundError, SourceResponseError, TransientSourceError

URL = "https://drp.b3.com.br/rapinegocios/tickercsv/PETR4/2026-11-19?type=2"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s

    def clock(self) -> float:
        return self.now


def _client(handler: object, clock: FakeClock, **kw: object) -> PoliteClient:
    params: dict[str, object] = {
        "requests_per_second": 1.0, "timeout_s": 5, "max_attempts": 3, "backoff_base_s": 2.0,
        "user_agent": "Mozilla/5.0 (compatible; teste)",
    }  # fmt: skip
    params.update(kw)
    return PoliteClient(
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        sleep=clock.sleep,
        clock=clock.clock,
        **params,  # type: ignore[arg-type]
    )


def test_paces_requests_and_sends_generic_user_agent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"ok")

    clock = FakeClock()
    client = _client(handler, clock)
    client.get(URL, max_bytes=10)
    client.get(URL, max_bytes=10)
    assert clock.sleeps == [1.0]  # 1 req/s
    assert seen[0].headers["user-agent"] == "Mozilla/5.0 (compatible; teste)"
    assert "cookie" not in seen[0].headers


def test_retries_transient_with_exponential_backoff() -> None:
    statuses = iter([503, 429, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(statuses), content=b"ok")

    clock = FakeClock()
    assert _client(handler, clock, requests_per_second=1000).get(URL, max_bytes=10).content == b"ok"
    backoffs = [s for s in clock.sleeps if s >= 1]
    assert backoffs == [2.0, 4.0]


def test_gives_up_after_max_attempts() -> None:
    clock = FakeClock()
    with pytest.raises(TransientSourceError, match="403"):
        _client(lambda r: httpx.Response(403), clock).get(URL, max_bytes=10)


def test_404_is_permanent_and_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(404)

    with pytest.raises(SourceNotFoundError):
        _client(handler, FakeClock()).get(URL, max_bytes=10)
    assert len(calls) == 1


def test_body_size_is_capped_during_download() -> None:
    with pytest.raises(SourceResponseError):
        _client(lambda r: httpx.Response(200, content=b"x" * 100), FakeClock()).get(URL, max_bytes=10)


@pytest.mark.parametrize("url", ["http://drp.b3.com.br/x", "https://exemplo.com/x"])
def test_only_https_to_known_hosts(url: str) -> None:
    with pytest.raises(SourceResponseError):
        _client(lambda r: httpx.Response(200), FakeClock()).get(url, max_bytes=10)


def test_redirect_to_unknown_host_is_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://exemplo.com/roubo"})

    with pytest.raises(SourceResponseError):
        _client(handler, FakeClock()).get(URL, max_bytes=10)
