from __future__ import annotations

import socket

import pytest

import laptop_backup_ssh_endpoint as endpoint


def answer(address: str) -> tuple[object, ...]:
    return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, 22))


@pytest.mark.parametrize("value", ("10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.20.19"))
def test_accepts_only_canonical_rfc1918_ipv4(value: str) -> None:
    assert endpoint.lan_ipv4(value) == value


@pytest.mark.parametrize(
    "value",
    ("100.78.28.10", "192.0.2.10", "127.0.0.1", "169.254.1.1", "fe80::1", "bad", "192.168.020.019"),
)
def test_rejects_tailscale_public_ipv6_and_malformed_candidates(value: str) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        endpoint.lan_ipv4(value)


def test_requires_exactly_one_distinct_candidate() -> None:
    assert endpoint.select_endpoint(("192.168.20.19", "192.168.20.19")) == "192.168.20.19"
    with pytest.raises(ValueError, match="exactly one"):
        endpoint.select_endpoint(())
    with pytest.raises(ValueError, match="exactly one"):
        endpoint.select_endpoint(("192.168.20.19", "192.168.20.20"))


def test_discovers_fixed_ar_local_name(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    def getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        calls.append((*args, kwargs))
        return [answer("192.168.20.19")]

    monkeypatch.setattr(endpoint.socket, "getaddrinfo", getaddrinfo)
    assert endpoint.discover_endpoint("ar.local") == "192.168.20.19"
    assert calls and calls[0][0:2] == ("ar.local", 22)
    with pytest.raises(ValueError, match="protected contract"):
        endpoint.discover_endpoint("ar-local-pi5")


def test_resolution_failure_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> list[tuple[object, ...]]:
        raise socket.gaierror("unavailable")

    monkeypatch.setattr(endpoint.socket, "getaddrinfo", fail)
    with pytest.raises(ValueError, match="discovery failed"):
        endpoint.discover_endpoint()
