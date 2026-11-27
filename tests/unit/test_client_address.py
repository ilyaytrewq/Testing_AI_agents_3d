from ipaddress import ip_network

import pytest
from starlette.requests import Request

from themed_chat.api.client_address import client_address

PROXIES = (ip_network("10.0.0.0/8"), ip_network("fd00::/8"))


def request(peer: str, *forwarded: str) -> Request:
    headers = [(b"x-forwarded-for", value.encode()) for value in forwarded]
    return Request({"type": "http", "client": (peer, 1234), "headers": headers})


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        # No trusted proxy configured or untrusted peer: the header is ignored (spoofing).
        ("203.0.113.9", ["198.51.100.1"], "203.0.113.9"),
        # Behind trusted proxies: the right-most hop that is not a proxy.
        ("10.0.0.2", ["198.51.100.1"], "198.51.100.1"),
        ("10.0.0.2", ["6.6.6.6, 198.51.100.1, 10.0.0.3"], "198.51.100.1"),
        ("10.0.0.2", ["6.6.6.6", "198.51.100.1"], "198.51.100.1"),
        ("fd00::2", ["2001:db8::1"], "2001:db8::1"),
        # Nothing usable: the peer.
        ("10.0.0.2", [], "10.0.0.2"),
        ("10.0.0.2", ["10.0.0.3"], "10.0.0.2"),
        ("10.0.0.2", ["6.6.6.6, garbage"], "10.0.0.2"),
    ],
)
def test_client_address(peer: str, forwarded: list[str], expected: str) -> None:
    assert client_address(request(peer, *forwarded), PROXIES) == expected


def test_without_trusted_proxies_the_header_never_counts() -> None:
    assert client_address(request("10.0.0.2", "198.51.100.1"), ()) == "10.0.0.2"


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("10.0.0.2", ["1.2.3.4:5555"], "1.2.3.4"),
        ("10.0.0.2", ["[2001:db8::1]:443"], "2001:db8::1"),
        ("10.0.0.2", ["1.2.3.4, 10.0.0.3:8080"], "1.2.3.4"),
        # IPv4-mapped IPv6 peers and hops match IPv4 ranges.
        ("::ffff:10.0.0.2", ["198.51.100.1"], "198.51.100.1"),
        ("10.0.0.2", ["1.2.3.4, ::ffff:10.0.0.3"], "1.2.3.4"),
        ("10.0.0.2", ["::ffff:198.51.100.7"], "198.51.100.7"),
        ("::ffff:203.0.113.9", ["198.51.100.1"], "203.0.113.9"),
        ("10.0.0.2", ["[2001:db8::1]junk"], "10.0.0.2"),
    ],
)
def test_ports_and_mapped_addresses(peer: str, forwarded: list[str], expected: str) -> None:
    assert client_address(request(peer, *forwarded), PROXIES) == expected
