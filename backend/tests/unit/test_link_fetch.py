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
