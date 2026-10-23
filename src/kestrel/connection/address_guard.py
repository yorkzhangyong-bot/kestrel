"""Hosted mode refuses local, private and metadata addresses before anything is sent (FR-028; research R8).

Accepted risk until public launch: the HTTP client resolves the name again when it connects, so a name whose
answer changes between this check and the connection (DNS rebinding) isn't caught.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Callable
from urllib.parse import urlsplit

Resolver = Callable[[str], list[str]]

_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")  # some cloud metadata services; not "private" to Python


def default_resolver(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)})


def is_allowed(url: str, mode: str, resolver: Resolver = default_resolver) -> bool:
    if mode == "local":
        return True
    host = (urlsplit(url).hostname or "").rstrip(".")
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return False
    try:
        return not _blocked(ipaddress.ip_address(host))
    except ValueError:
        pass  # a name, not an address literal
    try:
        addresses = resolver(host)
    except (OSError, UnicodeError):
        return True  # the test itself will report the name as unreachable
    for address in addresses:
        try:
            if _blocked(ipaddress.ip_address(address.split("%", 1)[0])):
                return False
        except ValueError:
            continue
    return True


def _blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_reserved
            or ip.is_multicast or (ip.version == 4 and ip in _SHARED_ADDRESS_SPACE))
