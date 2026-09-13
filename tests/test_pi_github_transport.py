"""Local protocol fixtures only; no GitHub requests or real credentials."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time

import pytest

import pi_github_alerts as alerts


@contextmanager
def server(handler):
    service = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    service.daemon_threads = True
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(service.server_port)
    finally:
        service.shutdown(); service.server_close(); thread.join(2)


class QuietHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass


def test_real_recovery_403_stays_queued_while_later_incident_is_created(tmp_path, monkeypatch):
    store = alerts.AlertStore(tmp_path / 'spool', repository='unit/repo')
    store.observe('delivery-test:707', 'Delivery test', 'DELIVERY_TEST', healthy=False)
    state = store.read(); old = state['incidents']['delivery-test:707']
    old.update(issue_number=707, delivered_revision=1)
    store.write(state)
    existing = {'number': 707, 'body': old['marker']}
    store.observe('delivery-test:707', 'Delivery test', 'DELIVERY_TEST', healthy=True)
    store.observe('drive-access', 'Drive access problem', 'AUTH_REVOKED', healthy=False)
    calls = []
    class Handler(QuietHandler):
        def reply(self, status, body):
            raw = json.dumps(body).encode()
            self.send_response(status); self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
        def do_GET(self):
            calls.append(('GET', self.path))
            self.reply(200, existing if self.path == '/issues/707' else [existing])
        def do_PATCH(self):
            self.rfile.read(int(self.headers['Content-Length']))
            calls.append(('PATCH', self.path))
            self.reply(403, {'message': 'unit-secret provider response'})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(('POST', self.path)); self.reply(201, {**body, 'number': 708})
    with server(Handler) as url:
        children = local_worker(tmp_path, monkeypatch, url)
        result = store.flush(alerts.GitHub('unit/repo', 'unit-secret'))
    assert result['result'] == 'QUEUED' and result['issues'] == [708]
    assert result['outcomes'][0]['category'] == 'GITHUB_HTTP_403'
    assert 'unit-secret' not in json.dumps(result)
    assert [method for method, _ in calls] == ['GET', 'PATCH', 'GET', 'POST']
    assert all(child.poll() == 0 for child, _, _ in children)
    rows = store.read()['incidents']
    assert rows['delivery-test:707']['delivered_revision'] == 1
    assert rows['drive-access']['issue_number'] == 708 and rows['drive-access']['delivered_revision'] == 1


def local_worker(tmp_path, monkeypatch, destination, *, before=""):
    """Run the actual worker entrypoint, changing only its test transport target."""
    source = str(Path(alerts.__file__).resolve())
    worker = tmp_path / "local_http_worker.py"
    worker.write_text(
        "import runpy, urllib.request\n" + before + "\n"
        "original = urllib.request.Request\n"
        "def local_request(url, *args, **kwargs):\n"
        "    prefix = 'https://api.github.com/repos/unit/repo/'\n"
        "    assert url.startswith(prefix), 'unexpected test endpoint'\n"
        "    return original(" + repr(destination + "/") + " + url[len(prefix):], *args, **kwargs)\n"
        "urllib.request.Request = local_request\n"
        "runpy.run_path(" + repr(source) + ", run_name='__main__')\n",
        encoding="utf-8")
    monkeypatch.setattr(alerts, "__file__", str(worker))
    spawned = []
    native_popen = subprocess.Popen
    def popen(*args, **kwargs):
        child = native_popen(*args, **kwargs)
        spawned.append((child, args[0], kwargs))
        return child
    monkeypatch.setattr(alerts.subprocess, "Popen", popen)
    return spawned


def test_actual_worker_stdin_secret_and_no_inherited_proxy(tmp_path, monkeypatch):
    received = []
    class Handler(QuietHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append((self.path, self.headers["Authorization"], json.loads(body)))
            raw = b'{"number":17,"body":"unit issue"}'
            self.send_response(201); self.send_header("Content-Length", str(len(raw)))
            self.end_headers(); self.wfile.write(raw)
    monkeypatch.setenv("GH_TOKEN", "unit-env-token")
    monkeypatch.setenv("GITHUB_TOKEN", "unit-other-env-token")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    with server(Handler) as url:
        spawned = local_worker(tmp_path, monkeypatch, url)
        result = alerts.GitHub("unit/repo", "unit-stdin-secret").request("POST", "issues", {"title": "unit"})
    assert result == {"number": 17, "body": "unit issue"}
    assert received == [("/issues", "Bearer unit-stdin-secret", {"title": "unit"})]
    assert len(spawned) == 1
    child, command, options = spawned[0]
    assert child.poll() == 0
    assert not any("unit-stdin-secret" in value for value in command)
    assert "GH_TOKEN" not in options["env"] and "GITHUB_TOKEN" not in options["env"]


def test_actual_redirect_never_forwards_authorization_or_issue_body(tmp_path, monkeypatch):
    destinations = []
    class Destination(QuietHandler):
        def do_POST(self):
            destinations.append(self.path)
            self.send_response(200); self.end_headers()
        do_GET = do_POST
    with server(Destination) as destination:
        class Redirect(QuietHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(307)
                self.send_header("Location", destination + "/credential-sink")
                self.send_header("Content-Length", "0"); self.end_headers()
        with server(Redirect) as url:
            local_worker(tmp_path, monkeypatch, url)
            with pytest.raises(alerts.DeliveryError, match="^GITHUB_HTTP_307$"):
                alerts.GitHub("unit/repo", "unit-only-secret").request("POST", "issues", {"title": "unit body"})
    assert destinations == []


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_real_trickled_response_obeys_remaining_deadline_and_reaps_worker(tmp_path, monkeypatch, phase):
    entered = threading.Event()
    class Trickle(QuietHandler):
        def do_GET(self):
            entered.set()
            try:
                initial = (b"HTTP/1.1 200 OK\r\nX-Unit: " if phase == "headers" else
                           b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
                self.wfile.write(initial); self.wfile.flush()
                for _ in range(40):
                    self.wfile.write(b" "); self.wfile.flush(); time.sleep(0.04)
            except (BrokenPipeError, ConnectionResetError):
                pass
    with server(Trickle) as url:
        spawned = local_worker(tmp_path, monkeypatch, url)
        client = alerts.GitHub("unit/repo", "unit-only-secret")
        client.deadline = time.monotonic() + 0.65
        began = time.monotonic()
        with pytest.raises(alerts.DeliveryError, match="^GITHUB_REQUEST_TIMEOUT$"):
            client.request("GET", "issues")
        assert time.monotonic() - began < 1.5
        assert entered.is_set()  # A real response started before cancellation.
        assert len(spawned) == 1 and spawned[0][0].poll() is not None


def test_blocked_dns_is_terminated_by_outer_worker_deadline(tmp_path, monkeypatch):
    entered = tmp_path / "dns-entered"
    before = (
        "import socket, time\nfrom pathlib import Path\n"
        "def blocked_dns(*args, **kwargs):\n"
        "    Path(" + repr(str(entered)) + ").write_text('entered')\n"
        "    time.sleep(10)\n"
        "socket.getaddrinfo = blocked_dns\n")
    spawned = local_worker(tmp_path, monkeypatch, "http://127.0.0.1:1", before=before)
    client = alerts.GitHub("unit/repo", "unit-only-secret")
    client.deadline = time.monotonic() + 0.65
    began = time.monotonic()
    with pytest.raises(alerts.DeliveryError, match="^GITHUB_REQUEST_TIMEOUT$"):
        client.request("GET", "issues")
    assert time.monotonic() - began < 1.5 and entered.exists()
    assert len(spawned) == 1 and spawned[0][0].poll() is not None


def test_exhausted_delivery_budget_never_starts_worker(monkeypatch):
    client = alerts.GitHub("unit/repo", "unit-only-secret")
    client.deadline = time.monotonic() - 1
    monkeypatch.setattr(alerts.subprocess, "run", lambda *a, **kw: pytest.fail("deadline launched worker"))
    with pytest.raises(alerts.DeliveryError, match="^GITHUB_DELIVERY_DEADLINE$"):
        client.request("POST", "issues", {})


@pytest.mark.parametrize("status,body,expected", [
    (403, b'{"message":"unit-only-secret private-provider-response"}', "GITHUB_HTTP_403"),
    (200, b'private-provider-response unit-only-secret', "GITHUB_UNAVAILABLE_OR_INVALID_RESPONSE"),
    (200, b'x' * (alerts.MAX_BYTES + 1), "GITHUB_RESPONSE_TOO_LARGE"),
], ids=["http-error-redacted", "invalid-json-redacted", "oversized-response"])
def test_provider_failure_and_oversize_never_escape_worker(tmp_path, monkeypatch, status, body, expected, capsys):
    class Handler(QuietHandler):
        def do_GET(self):
            try:
                self.send_response(status); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
    with server(Handler) as url:
        spawned = local_worker(tmp_path, monkeypatch, url)
        with pytest.raises(alerts.DeliveryError) as error:
            alerts.GitHub("unit/repo", "unit-only-secret").request("GET", "issues")
    assert str(error.value) == expected
    assert len(spawned) == 1  # No automatic transport retry.
    assert capsys.readouterr() == ("", "")
