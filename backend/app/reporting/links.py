"""Fetching a link a student pasted, safely (REP-04, requirements §11 "Security").

A URL in a report is user input, and fetching it turns this server into a client whose destination
someone else chooses. That is the shape of an SSRF, and the defence has to be about *where* the
request may go rather than about what comes back.

So the check is on the resolved address, not the hostname: a name can point anywhere, and a name
the professor trusts today can point at the metadata endpoint tomorrow. Every redirect is checked
the same way, because a redirect is just a second request someone else chose.

The fetch itself is bounded in three directions — scheme, size, and time — so a link cannot become
a way to occupy the worker.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

log = logging.getLogger(__name__)

ALLOWED_SCHEMES = frozenset({"http", "https"})
MAX_BYTES = 5 * 1024 * 1024  # architecture §5.6
TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 3


class LinkRefusedError(Exception):
    """The URL was refused before any request was made. The message is shown to the student."""


@dataclass(frozen=True, slots=True)
class CheckedUrl:
    url: str
    host: str
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Fetched:
    url: str
    content_type: str
    data: bytes
    truncated: bool = False


Resolver = Callable[[str], list[str]]


def _default_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    return [str(info[4][0]) for info in infos]


def is_public_address(address: str) -> bool:
    """Everything that is not ordinary public routing is refused, including the ambiguous cases.

    `is_global` already excludes loopback, link-local, private ranges and the metadata endpoint at
    169.254.169.254; the extra checks below are belt and braces for addresses whose classification
    has changed between Python versions.
    """
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.is_private or parsed.is_loopback or parsed.is_link_local:
        return False
    if parsed.is_reserved or parsed.is_multicast or parsed.is_unspecified:
        return False
    return bool(parsed.is_global)


def check_url(url: str, *, resolve: Resolver | None = None) -> CheckedUrl:
    """Refuse anything we should not fetch, before fetching anything."""
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise LinkRefusedError(
            f"only http and https links can be fetched; this one uses the "
            f"{parsed.scheme or 'missing'} scheme"
        )
    if parsed.username or parsed.password:
        raise LinkRefusedError(
            "a link with credentials in it is not fetched; remove them and re-add it"
        )
    host = parsed.hostname
    if not host:
        raise LinkRefusedError("the link has no host")

    addresses = (resolve or _default_resolver)(host)
    if not addresses:
        raise LinkRefusedError(f"the host {host} does not resolve")

    # Every address, not just the first: a name that resolves to one public and one private
    # address is a name that can be raced into reaching the private one.
    private = [address for address in addresses if not is_public_address(address)]
    if private:
        raise LinkRefusedError(
            f"{host} resolves to a private or reserved address, which this server will not fetch"
        )

    return CheckedUrl(url=parsed.geturl(), host=host, addresses=tuple(addresses))


async def fetch(url: str, *, resolve: Resolver | None = None) -> Fetched:
    """Fetch a checked URL, bounded in size and time, re-checking every redirect.

    The size bound is applied while reading, not after: see the comment in the loop.
    """
    import httpx

    checked = check_url(url, resolve=resolve)
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
        current = checked.url
        for _ in range(MAX_REDIRECTS + 1):
            # Streamed, so the size bound bounds the *download* and not just what is kept. Reading
            # `response.content` first would buffer the whole body before the slice, which makes
            # the 5 MB cap a truncation rather than a limit: one link to an endless response is
            # then enough to exhaust the worker.
            async with client.stream("GET", current, headers={"Accept": "*/*"}) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    if not location:
                        raise LinkRefusedError("the server redirected without saying where")
                    # A redirect is a second request to a destination someone else chose.
                    current = check_url(str(response.url.join(location)), resolve=resolve).url
                    continue

                response.raise_for_status()
                body = bytearray()
                truncated = False
                async for piece in response.aiter_bytes():
                    body.extend(piece)
                    if len(body) > MAX_BYTES:
                        del body[MAX_BYTES:]
                        truncated = True
                        break

                return Fetched(
                    url=current,
                    content_type=response.headers.get("content-type", "application/octet-stream"),
                    data=bytes(body),
                    truncated=truncated,
                )

    raise LinkRefusedError(f"the link redirected more than {MAX_REDIRECTS} times")
