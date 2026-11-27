from collections.abc import Sequence
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network, ip_address

from starlette.requests import Request

Network = IPv4Network | IPv6Network


def parse_address(value: str) -> IPv4Address | IPv6Address | None:
    """An address from a peer or X-Forwarded-For hop, with any port removed.

    Accepts "1.2.3.4", "1.2.3.4:5555", "2001:db8::1" and "[2001:db8::1]:443". An IPv4-mapped
    IPv6 address (::ffff:1.2.3.4) becomes the IPv4 address, so IPv4 ranges match it.
    """
    text = value.strip()
    if text.startswith("["):
        end = text.find("]")
        if end == -1 or (text[end + 1 :] and not text[end + 1 :].startswith(":")):
            return None
        text = text[1:end]
    elif text.count(":") == 1:
        text = text.split(":", 1)[0]
    try:
        address = ip_address(text)
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _trusted(address: IPv4Address | IPv6Address, proxies: Sequence[Network]) -> bool:
    return any(address in network for network in proxies)


def client_address(request: Request, trusted_proxies: Sequence[Network]) -> str:
    """The TCP peer, or, behind a trusted proxy, the nearest untrusted X-Forwarded-For hop.

    X-Forwarded-For is read only when the peer itself is a trusted proxy, so a client that
    connects directly cannot choose its own address. Hops are read from the right: each
    trusted proxy appends the address it saw, and the first one that is not a trusted proxy
    is the client.
    """
    raw_peer = request.client.host if request.client else "unknown"
    peer = parse_address(raw_peer)
    if peer is None:
        return raw_peer
    if not trusted_proxies or not _trusted(peer, trusted_proxies):
        return str(peer)
    hops = [
        hop.strip()
        for header in request.headers.getlist("x-forwarded-for")
        for hop in header.split(",")
    ]
    for hop in reversed(hops):
        if not hop:
            continue
        address = parse_address(hop)
        if address is None:
            return str(peer)  # A malformed hop: nothing to its left can be trusted.
        if not _trusted(address, trusted_proxies):
            return str(address)
    return str(peer)
