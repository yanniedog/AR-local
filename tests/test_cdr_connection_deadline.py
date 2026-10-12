"""Multiple public DNS addresses and TLS share one connection time budget."""
import ssl
from io import BytesIO
from unittest.mock import Mock

import pytest

import cdr_http_policy as policy
from tests.test_cdr_http_policy import resolver_for


def connection(monkeypatch, clock):
    monkeypatch.setattr(policy.time, "monotonic", lambda: clock[0])
    target = policy.resolve_public_https_url("https://bank.example/products",
                                             resolver=resolver_for("8.8.8.8", "9.9.9.9"))
    return policy._PinnedHTTPSConnection(target, timeout=8, context=ssl.create_default_context())


def test_stalled_first_address_cannot_spend_another_full_timeout(monkeypatch):
    clock, calls = [0.0], []
    conn = connection(monkeypatch, clock)
    def stalled(address, timeout, source):
        calls.append((address, timeout))
        clock[0] += timeout
        raise TimeoutError("connect")
    monkeypatch.setattr(policy.socket, "create_connection", stalled)
    with pytest.raises(TimeoutError):
        conn.connect()
    assert calls == [(("8.8.8.8", 443), 8)]
    assert clock[0] == 8


def test_fallback_and_tls_only_receive_remaining_budget(monkeypatch):
    clock, timeouts = [0.0], []
    conn = connection(monkeypatch, clock)
    raw, tls = Mock(), Mock()
    def connect(address, timeout, source):
        timeouts.append(timeout)
        clock[0] += 3
        if len(timeouts) == 1:
            raise OSError("unreachable")
        return raw
    monkeypatch.setattr(policy.socket, "create_connection", connect)
    context = Mock()
    context.wrap_socket.return_value = tls
    conn._context = context
    tls.do_handshake.side_effect = lambda: clock.__setitem__(0, clock[0] + 1)
    conn.connect()
    assert timeouts == [8, 5]
    raw.settimeout.assert_called_once_with(2)
    context.wrap_socket.assert_called_once_with(raw, server_hostname="bank.example",
                                               do_handshake_on_connect=False)
    assert [c.args[0] for c in tls.settimeout.call_args_list] == [2, 1]
    assert conn.peer_ip == "9.9.9.9"


def test_tls_exhaustion_closes_socket_and_stops_address_fallback(monkeypatch):
    clock = [0.0]
    conn = connection(monkeypatch, clock)
    raw, tls, context = Mock(), Mock(), Mock()
    dial = Mock(return_value=raw)
    monkeypatch.setattr(policy.socket, "create_connection", dial)
    context.wrap_socket.return_value = tls
    conn._context = context
    tls.do_handshake.side_effect = lambda: clock.__setitem__(0, 8)
    with pytest.raises(TimeoutError):
        conn.connect()
    assert dial.call_count == 1
    tls.close.assert_called_once()
    assert conn.sock is None and conn.peer_ip is None


def test_successful_address_fallback_can_finish_its_http_request(monkeypatch):
    conn = connection(monkeypatch, [0.0])
    raw, tls, context = Mock(), Mock(), Mock()
    monkeypatch.setattr(policy.socket, "create_connection", Mock(side_effect=[OSError("unreachable"), raw]))
    context.wrap_socket.return_value = tls
    tls.makefile.return_value = BytesIO(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}")
    conn._context = context
    conn.request("GET", "/products")
    response = conn.getresponse()
    assert response.status == 200 and response.read() == b"{}"


@pytest.mark.parametrize("close_phase", ["settimeout", "do_handshake"])
def test_timeout_closure_during_tls_is_a_transport_error(monkeypatch, close_phase):
    clock = [0.0]
    conn = connection(monkeypatch, clock)
    raw, tls, context = Mock(), Mock(), Mock()
    monkeypatch.setattr(policy.socket, "create_connection", Mock(return_value=raw))
    context.wrap_socket.return_value = tls
    conn._context = context
    def close():
        conn.close()
        clock[0] = 8
    getattr(tls, close_phase).side_effect = lambda *a: close()
    with pytest.raises(OSError):
        conn.connect()
    assert conn.sock is None and conn.peer_ip is None
