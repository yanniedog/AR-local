"""HTTP transport fixtures; these do not constitute dashboard/CDR acceptance."""
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import verify_local


@pytest.fixture
def endpoint_calls(monkeypatch):
    calls = []
    def get(url, timeout=30.0):
        calls.append((url, timeout))
        return 404 if url.endswith("api/energy") else 200
    monkeypatch.setattr(verify_local, "http_get", get)
    monkeypatch.setattr(verify_local.urllib.request, "urlopen", lambda *_args, **_kwargs:
        io.BytesIO(json.dumps({"run_date": "2026-09-12", "banks_counts": {"rates": 1}}).encode()))
    return calls


def test_default_deadline_remains_thirty_for_every_endpoint(endpoint_calls):
    assert verify_local.main(["--base-url=http://test.invalid/", "--require-banks-rates"]) == 0
    assert len(endpoint_calls) > 30
    assert {timeout for _, timeout in endpoint_calls} == {30.0}


def test_only_three_history_requests_receive_explicit_cold_deadline(endpoint_calls, capsys):
    assert verify_local.main(["--base-url=http://test.invalid/", "--require-banks-rates",
                              "--history-timeout-seconds=90", "--progress"]) == 0
    history = [(url, timeout) for url, timeout in endpoint_calls if "api/banks/history/section?" in url]
    assert len(history) == 3 and all(timeout == 90 for _, timeout in history)
    assert all(timeout == 30 for url, timeout in endpoint_calls if "api/banks/history/section?" not in url)
    output = capsys.readouterr().out
    assert "GET http://test.invalid/api/banks/history/section" in output
    assert "timeout=90s" in output and "elapsed=" in output and "GET JSON" in output


@pytest.mark.parametrize("value", ["0", "-1", "91", "nan", "inf"])
def test_unbounded_or_invalid_deadline_is_rejected(endpoint_calls, value):
    with pytest.raises(SystemExit) as error:
        verify_local.main(["--history-timeout-seconds=" + value])
    assert error.value.code == 2 and endpoint_calls == []


@pytest.mark.parametrize("status", [-1, 404, 503])
def test_history_timeout_or_non200_still_fails(endpoint_calls, monkeypatch, capsys, status):
    original = verify_local.http_get
    monkeypatch.setattr(verify_local, "http_get", lambda url, timeout=30:
        status if "api/banks/history/section?" in url else original(url, timeout))
    assert verify_local.main(["--base-url=http://test.invalid/", "--history-timeout-seconds=90"]) == 1
    assert "history/section" in capsys.readouterr().err


def test_actual_delayed_headers_obey_selected_request_deadline():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(0.2)
            try:
                self.send_response(200)
                self.end_headers()
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *_args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/transport-fixture"
        assert verify_local.http_get(url, timeout=0.05) == -1
        assert verify_local.http_get(url, timeout=1) == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert not thread.is_alive()
