"""Select one untrusted LAN route for the pinned AR-local SSH identity."""

from __future__ import annotations

import argparse
import ipaddress
import socket
from collections.abc import Iterable


LOGICAL_HOST = "ar-local-pi5"
DISCOVERY_NAME = "ar.local"
RFC1918 = tuple(
    ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def lan_ipv4(value: object) -> str:
    """Return one canonical RFC1918 IPv4 address or fail closed."""
    text = str(value)
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError("SSH discovery returned a malformed endpoint") from exc
    if not isinstance(address, ipaddress.IPv4Address) or not any(
        address in network for network in RFC1918
    ):
        raise ValueError("SSH discovery returned a non-LAN IPv4 endpoint")
    if text != str(address):
        raise ValueError("SSH discovery returned a non-canonical endpoint")
    return text


def select_endpoint(candidates: Iterable[object]) -> str:
    """Require exactly one distinct, canonical LAN candidate."""
    selected = {lan_ipv4(candidate) for candidate in candidates}
    if len(selected) != 1:
        raise ValueError("SSH discovery must return exactly one LAN endpoint")
    return selected.pop()


def discover_endpoint(name: str = DISCOVERY_NAME) -> str:
    """Resolve only the fixed LAN mDNS name; host-key pinning supplies authority."""
    if name != DISCOVERY_NAME:
        raise ValueError("SSH discovery name differs from the protected contract")
    try:
        answers = socket.getaddrinfo(
            name, 22, family=socket.AF_INET, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP
        )
    except OSError as exc:
        raise ValueError("SSH LAN endpoint discovery failed") from exc
    return select_endpoint(answer[4][0] for answer in answers)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    print(discover_endpoint(args.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
