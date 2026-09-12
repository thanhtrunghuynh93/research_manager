"""Fetching a link a student pasted (REP-04, requirements §11 "Security").

A URL in a report is text a user supplied, and fetching it makes this server into a client that
someone else chooses the destination for. The guard is therefore about where a request may go, not
about what comes back: no private address, no loopback, no cloud metadata endpoint, no scheme that
is not http or https, and no redirect that quietly arrives at one of those.
"""

from __future__ import annotations

import pytest

from app.reporting.links import MAX_BYTES, LinkRefusedError, check_url, is_public_address

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/data.csv",
        "gopher://example.com/",
        "data:text/plain;base64,aGk=",
        "javascript:alert(1)",
    ],
)
def test_only_http_and_https_are_fetchable(url: str) -> None:
    with pytest.raises(LinkRefusedError, match="scheme"):
        check_url(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "::1",
        "10.0.0.5",
        "172.16.4.9",
        "192.168.1.1",
        "169.254.169.254",  # the cloud metadata endpoint, which is the classic target
        "0.0.0.0",  # noqa: S104 - an address under test, not a bind target
        "fd00::1",
    ],
)
def test_no_request_may_reach_a_private_or_link_local_address(address: str) -> None:
    assert is_public_address(address) is False


@pytest.mark.parametrize(
    "address", ["93.184.216.34", "8.8.8.8", "2606:2800:220:1:248:1893:25c8:1946"]
)
def test_ordinary_public_addresses_are_allowed(address: str) -> None:
    assert is_public_address(address) is True


def test_a_hostname_that_resolves_to_loopback_is_refused() -> None:
    """The check is on the resolved address, because a name can point anywhere."""
    with pytest.raises(LinkRefusedError, match="private"):
        check_url("http://localhost:8000/admin", resolve=lambda host: ["127.0.0.1"])


def test_a_hostname_that_resolves_nowhere_is_refused_rather_than_attempted() -> None:
    with pytest.raises(LinkRefusedError, match="resolve"):
        check_url("https://nowhere.invalid/x", resolve=lambda host: [])


def test_a_public_url_passes_and_comes_back_normalised() -> None:
    checked = check_url("https://arxiv.org/abs/2401.00001", resolve=lambda host: ["93.184.216.34"])

    assert checked.host == "arxiv.org"
    assert checked.url.startswith("https://")


def test_a_url_with_credentials_in_it_is_refused() -> None:
    """Credentials in a URL would be sent onward by us, which is not ours to do."""
    with pytest.raises(LinkRefusedError, match="credential"):
        check_url("https://user:token@example.com/data", resolve=lambda host: ["93.184.216.34"])


def test_the_size_cap_is_stated_rather_than_discovered_mid_download() -> None:
    assert MAX_BYTES == 5 * 1024 * 1024


# ------------------------------------------------------------------ the fetch itself


class _Transport:
    """A scripted server, so the redirect handling can be exercised without one."""

    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.requested: list[str] = []

    def handle(self, request: object) -> object:
        self.requested.append(str(request.url))  # type: ignore[attr-defined]
        return self.responses.pop(0)


def _client(transport: _Transport) -> object:
    import httpx

    return httpx.MockTransport(lambda request: transport.handle(request))  # type: ignore[arg-type]


async def _fetch_with(monkeypatch, transport: _Transport, url: str, resolve):
    import httpx

    from app.reporting import links

    original = httpx.AsyncClient

    def _factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("follow_redirects", None)
        return original(*args, transport=_client(transport), follow_redirects=False, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return await links.fetch(url, resolve=resolve)


async def test_a_public_link_is_fetched_and_its_content_type_kept(monkeypatch) -> None:
    import httpx

    transport = _Transport(
        httpx.Response(200, content=b"# notes", headers={"content-type": "text/markdown"})
    )

    fetched = await _fetch_with(
        monkeypatch, transport, "https://example.com/notes.md", lambda host: ["93.184.216.34"]
    )

    assert fetched.data == b"# notes"
    assert fetched.content_type.startswith("text/markdown")


async def test_a_redirect_to_a_private_address_is_refused_at_the_second_hop(monkeypatch) -> None:
    """The classic SSRF: a public URL that bounces to the metadata endpoint."""
    import httpx

    from app.reporting.links import LinkRefusedError

    transport = _Transport(
        httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"})
    )

    def _resolve(host: str) -> list[str]:
        return ["169.254.169.254"] if host == "169.254.169.254" else ["93.184.216.34"]

    with pytest.raises(LinkRefusedError, match="private"):
        await _fetch_with(monkeypatch, transport, "https://example.com/go", _resolve)


async def test_a_redirect_to_another_public_address_is_followed(monkeypatch) -> None:
    import httpx

    transport = _Transport(
        httpx.Response(302, headers={"location": "https://example.com/final"}),
        httpx.Response(200, content=b"arrived", headers={"content-type": "text/plain"}),
    )

    fetched = await _fetch_with(
        monkeypatch, transport, "https://example.com/start", lambda host: ["93.184.216.34"]
    )

    assert fetched.data == b"arrived"
    assert len(transport.requested) == 2


async def test_a_redirect_with_no_destination_is_refused(monkeypatch) -> None:
    import httpx

    from app.reporting.links import LinkRefusedError

    transport = _Transport(httpx.Response(302))

    with pytest.raises(LinkRefusedError, match="redirected without saying where"):
        await _fetch_with(
            monkeypatch, transport, "https://example.com/go", lambda host: ["93.184.216.34"]
        )


async def test_an_endless_redirect_chain_gives_up(monkeypatch) -> None:
    import httpx

    from app.reporting.links import MAX_REDIRECTS, LinkRefusedError

    transport = _Transport(
        *[
            httpx.Response(302, headers={"location": f"https://example.com/{index}"})
            for index in range(MAX_REDIRECTS + 2)
        ]
    )

    with pytest.raises(LinkRefusedError, match="redirected more than"):
        await _fetch_with(
            monkeypatch, transport, "https://example.com/go", lambda host: ["93.184.216.34"]
        )


async def test_a_body_over_the_cap_is_truncated_and_says_so(monkeypatch) -> None:
    import httpx

    from app.reporting.links import MAX_BYTES

    transport = _Transport(
        httpx.Response(
            200, content=b"x" * (MAX_BYTES + 1000), headers={"content-type": "text/plain"}
        )
    )

    fetched = await _fetch_with(
        monkeypatch, transport, "https://example.com/big", lambda host: ["93.184.216.34"]
    )

    assert len(fetched.data) == MAX_BYTES
    assert fetched.truncated is True
