"""Protocol/custody fixtures only; no Google account or business acceptance data."""
from contextlib import contextmanager
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import pytest

import pi_drive_access_probe as probe

REPOSITORY = "rclone:fixture:Fixture folder/restic"
INI = (b'[fixture]\ntype=drive\nscope=drive.file\nclient_id=123-unit.apps.googleusercontent.com\n'
       b'client_secret=plain-unit-secret\ntoken={"refresh_token":"unit-refresh","access_token":"old-unit-access"}\n')


@pytest.fixture
def protocol(tmp_path, monkeypatch):
    path = tmp_path / "config.conf"
    path.write_bytes(INI)
    monkeypatch.setattr(probe, "_read_private", lambda p: p.read_bytes())
    state = {"requests": [], "fault": None}
    def transport(request, seconds):
        assert 0 < seconds <= 10
        state["requests"].append(request)
        url = urllib.parse.urlsplit(request.full_url)
        query = urllib.parse.parse_qs(url.query)
        kind = "media" if query.get("alt") == ["media"] else url.path.rsplit("/", 1)[-1]
        if state["fault"]:
            override = state["fault"](request, kind, query)
            if override is not None:
                return override
        if kind == "token":
            body = {"access_token": "new-unit-access", "token_type": "Bearer", "expires_in": 3600, "scope": probe.SCOPE}
        elif kind == "about":
            body = {"storageQuota": {"usage": "100", "limit": "1000"}}
        elif kind == "files":
            q = query["q"][0]
            if "name = 'Fixture folder'" in q: identifier, name, folder = "folder1", "Fixture folder", True
            elif "name = 'restic'" in q: identifier, name, folder = "folder2", "restic", True
            else: identifier, name, folder = "config1", "config", False
            body = {"files": [{"id": identifier, "name": name, "mimeType": probe.FOLDER if folder else "application/octet-stream", "trashed": False}]}
        elif kind == "folder2":
            body = {"id": "folder2", "mimeType": probe.FOLDER, "trashed": False, "capabilities": {"canAddChildren": True}}
        elif kind == "config1":
            body = {"id": "config1", "name": "config", "mimeType": "application/octet-stream", "trashed": False,
                    "size": "4", "capabilities": {"canDownload": True}}
        elif kind == "media":
            return 200, b"unit"
        else:
            raise AssertionError("unexpected protocol request")
        return 200, json.dumps(body).encode()
    monkeypatch.setattr(probe, "_transport", transport)
    state.update(path=path, run=lambda: probe._run(REPOSITORY, path))
    return state


def test_fresh_refresh_actual_folder_capabilities_and_content(protocol):
    before = protocol["path"].read_bytes()
    assert protocol["run"]() == {"status": "PASS", "category": "OK", "phase": "COMPLETE"}
    requests = protocol["requests"]
    assert len(requests) == 8
    assert requests[0].full_url == probe.TOKEN_URL
    form = urllib.parse.parse_qs(requests[0].data.decode())
    assert form == {"client_id": ["123-unit.apps.googleusercontent.com"], "client_secret": ["plain-unit-secret"],
                    "refresh_token": ["unit-refresh"], "grant_type": ["refresh_token"]}
    assert all(r.data is None and r.get_header("Authorization") == "Bearer new-unit-access" for r in requests[1:])
    assert all("unit-secret" not in r.full_url and "unit-refresh" not in r.full_url for r in requests)
    assert protocol["path"].read_bytes() == before


@pytest.mark.parametrize("code,error,category", [(400, "invalid_grant", "AUTH_REVOKED"),
    (401, "invalid_client", "AUTH_CLIENT"), (403, "access_denied", "PERMISSION"), (400, "invalid_scope", "SCOPE_INVALID")])
def test_refresh_failure_is_safe_and_never_uses_cached_access(protocol, code, error, category):
    protocol["fault"] = lambda request, kind, query: (code, json.dumps({"error": error, "error_description": "unit-refresh plain-unit-secret private-folder"}).encode())
    result = protocol["run"]()
    assert result == {"status": "FAIL", "category": category, "phase": "OAUTH_REFRESH"}
    assert len(protocol["requests"]) == 1


@pytest.mark.parametrize("code,reason,category", [(403, "storageQuotaExceeded", "STORAGE_QUOTA"),
    (403, "rateLimitExceeded", "API_RATE_LIMIT"), (403, "userRateLimitExceeded", "API_RATE_LIMIT"),
    (403, "accessNotConfigured", "API_DISABLED"), (403, "insufficientFilePermissions", "PERMISSION"),
    (429, "other", "API_RATE_LIMIT"), (401, "other", "AUTHORIZATION"), (503, "other", "API_ERROR")])
def test_drive_failures_are_classified_without_provider_text(protocol, code, reason, category):
    protocol["fault"] = lambda request, kind, query: (code, json.dumps({"error": {"message": "private-account unit-secret", "errors": [{"reason": reason}]}}).encode()) if kind == "about" else None
    result = protocol["run"]()
    assert result == {"status": "FAIL", "category": category, "phase": "QUOTA"}
    assert len(protocol["requests"]) == 2  # No automatic retries.


@pytest.mark.parametrize("quota,expected", [({"usage": "100", "limit": "100"}, "STORAGE_QUOTA"),
    ({"usage": "100"}, "OK"), ({"usage": "-1", "limit": "100"}, "RESPONSE_INVALID"),
    ({"usage": True, "limit": "100"}, "RESPONSE_INVALID"), ({}, "RESPONSE_INVALID")])
def test_storage_quota_checks_limit_and_unlimited_accounts(protocol, quota, expected):
    protocol["fault"] = lambda request, kind, query: (200, json.dumps({"storageQuota": quota}).encode()) if kind == "about" else None
    assert protocol["run"]()["category"] == expected


@pytest.mark.parametrize("field,kind,category", [("canAddChildren", "folder2", "WRITE_DENIED"), ("canDownload", "config1", "READ_DENIED")])
def test_required_capabilities_cannot_be_missing_or_false(protocol, field, kind, category):
    def fault(request, actual, query):
        if actual == kind:
            body = {"id": kind, "name": "config", "mimeType": probe.FOLDER if kind == "folder2" else "application/octet-stream",
                    "trashed": False, "size": "4", "capabilities": {field: False}}
            return 200, json.dumps(body).encode()
    protocol["fault"] = fault
    assert protocol["run"]()["category"] == category
    assert not any("alt=media" in r.full_url for r in protocol["requests"])


@pytest.mark.parametrize("fault_kind,category", [("missing", "REPOSITORY_MISSING"), ("duplicate", "REPOSITORY_AMBIGUOUS"),
    ("incomplete", "LIMIT_EXCEEDED"), ("pages", "LIMIT_EXCEEDED"), ("repeated_token", "RESPONSE_INVALID")])
def test_unique_complete_path_is_required(protocol, fault_kind, category):
    def fault(request, kind, query):
        if kind != "files": return None
        row = {"id": "folder1", "name": "Fixture folder", "mimeType": probe.FOLDER, "trashed": False}
        if fault_kind == "missing": body = {"files": []}
        elif fault_kind == "duplicate": body = {"files": [row, {**row, "id": "duplicate"}]}
        elif fault_kind == "incomplete": body = {"files": [row], "incompleteSearch": True}
        else: body = {"files": [], "nextPageToken": "same" if fault_kind == "repeated_token" else str(len(protocol["requests"]))}
        return 200, json.dumps(body).encode()
    protocol["fault"] = fault
    result = protocol["run"]()
    assert result["category"] == category and result["phase"] == "REPOSITORY"
    assert len(protocol["requests"]) <= 2 + probe.MAX_PAGES


def test_later_page_duplicate_is_not_hidden_by_first_match(protocol):
    def fault(request, kind, query):
        if kind == "files":
            row = {"id": "second" if "pageToken" in query else "first", "name": "Fixture folder", "mimeType": probe.FOLDER, "trashed": False}
            body = {"files": [row]}
            if "pageToken" not in query: body["nextPageToken"] = "next"
            return 200, json.dumps(body).encode()
    protocol["fault"] = fault
    assert protocol["run"]()["category"] == "REPOSITORY_AMBIGUOUS"


def test_exact_query_escaping_and_configured_root_folder(protocol):
    protocol["path"].write_bytes(INI + b'root_folder_id=known-root\n')
    assert protocol["run"]()["status"] == "PASS"
    queries = [urllib.parse.parse_qs(urllib.parse.urlsplit(r.full_url).query).get("q") for r in protocol["requests"]]
    assert any(q and "'known-root' in parents" in q[0] for q in queries)
    assert probe._escape("a'b\\c") == "a\\'b\\\\c"


@pytest.mark.parametrize("raw,category", [(INI.replace(b'scope=drive.file', b'scope=drive'), "SCOPE_INVALID"),
    (INI.replace(b'client_secret=plain-unit-secret', b'client_secret='), "CLIENT_MISSING"),
    (INI.replace(b'unit-refresh', b''), "GRANT_MISSING"), (INI + b'team_drive=other-tree\n', "CONFIG_INVALID"),
    (INI + b'token_url=https://untrusted.invalid/\n', "CONFIG_INVALID"), (b'[wrong]\ntype=drive\n', "CONFIG_INVALID")])
def test_invalid_or_rerouted_credentials_cannot_make_http_calls(protocol, raw, category):
    protocol["path"].write_bytes(raw)
    assert protocol["run"]()["category"] == category
    assert not protocol["requests"]


@pytest.mark.skipif(os.name != "posix", reason="Pi/POSIX custody; Windows ACLs are not claimed")
def test_private_file_missing_mode_symlink_and_no_mutation(tmp_path):
    path = tmp_path / "config"
    with pytest.raises(probe._Failure, match="CONFIG_MISSING"): probe._read_private(path)
    path.write_bytes(INI); path.chmod(0o644)
    with pytest.raises(probe._Failure, match="CONFIG_PERMISSIONS"): probe._read_private(path)
    path.chmod(0o600)
    assert probe._read_private(path) == INI
    link = tmp_path / "link"; link.symlink_to(path)
    with pytest.raises(probe._Failure, match="CONFIG_PERMISSIONS"): probe._read_private(link)


@pytest.mark.parametrize("raw", [b'', b'broken', b'{"storageQuota":{"usage":NaN}}'])
def test_bad_json_is_safe_failure(protocol, raw):
    protocol["fault"] = lambda request, kind, query: (200, raw) if kind == "about" else None
    assert protocol["run"]()["status"] == "FAIL"


def test_config_download_bytes_must_match_metadata(protocol):
    protocol["fault"] = lambda request, kind, query: (200, b'') if kind == "media" else None
    assert protocol["run"]() == {"status": "FAIL", "category": "RESPONSE_INVALID", "phase": "CONFIG_DOWNLOAD"}


def test_response_bound_checks_declared_actual_and_truncated_bytes():
    class Response(io.BytesIO):
        headers = {}
    response = Response(b'x'); response.headers = {'Content-Length': str(probe.MAX_BYTES + 1)}
    with pytest.raises(probe._Failure, match="LIMIT_EXCEEDED"): probe._body(response)
    assert response.tell() == 0
    with pytest.raises(probe._Failure, match="LIMIT_EXCEEDED"): probe._body(Response(b'x' * (probe.MAX_BYTES + 1)))
    response = Response(b'x'); response.headers = {'Content-Length': '3'}
    with pytest.raises(probe._Failure, match="RESPONSE_INVALID"): probe._body(response)


@contextmanager
def server(handler):
    service = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=service.serve_forever, daemon=True); thread.start()
    try: yield 'http://127.0.0.1:' + str(service.server_port)
    finally: service.shutdown(); service.server_close(); thread.join(2)


def test_actual_redirect_does_not_forward_form_or_authorization():
    received = []
    class Destination(BaseHTTPRequestHandler):
        def do_GET(self): received.append(self.path); self.send_response(200); self.end_headers()
        def do_POST(self): self.do_GET()
        def log_message(self, *args): pass
    with server(Destination) as target:
        class Redirect(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(307); self.send_header('Location', target + '/credential-sink'); self.send_header('Content-Length', '0'); self.end_headers()
            def log_message(self, *args): pass
        with server(Redirect) as source:
            request = urllib.request.Request(source, data=b'client_secret=unit-only', headers={'Authorization': 'Bearer unit-only'})
            code, body = probe._transport(request, 1)
    assert code == 307 and probe._error(code, body) == 'REDIRECT_REFUSED' and not received


def test_http_whole_deadline_covers_a_stalled_transport(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(probe, '_transport', lambda *args: (release.wait(2), b''))
    began = time.monotonic()
    try:
        with pytest.raises(probe._Failure, match='TIMEOUT'):
            probe._http(urllib.request.Request(probe.TOKEN_URL), began + 0.05)
        assert time.monotonic() - began < 0.5
    finally: release.set()


def test_actual_trickled_headers_cannot_extend_http_budget(monkeypatch):
    class Trickle(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Slow: '); self.wfile.flush()
                for _ in range(15):
                    time.sleep(0.04); self.wfile.write(b'a'); self.wfile.flush()
                self.wfile.write(b'\r\nContent-Length: 0\r\n\r\n'); self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError): pass
        def log_message(self, *args): pass
    with server(Trickle) as url:
        began = time.monotonic()
        with pytest.raises(probe._Failure, match='TIMEOUT'):
            probe._http(urllib.request.Request(url), began + 0.15)
        assert time.monotonic() - began < 0.5


def test_real_worker_timeout_is_bounded_and_reaped(tmp_path, monkeypatch):
    worker = tmp_path / 'worker.py'
    sentinel = tmp_path / 'completed'
    worker.write_text('import time\nfrom pathlib import Path\ntime.sleep(1)\nPath(' + repr(str(sentinel)) + ').write_text("alive")\n')
    monkeypatch.setattr(probe, '__file__', str(worker))
    monkeypatch.setattr(probe, 'TOTAL_SECONDS', 0.15)
    began = time.monotonic()
    assert probe.probe(REPOSITORY, tmp_path / 'private.conf') == {'status': 'FAIL', 'category': 'TIMEOUT', 'phase': 'PROBE'}
    assert time.monotonic() - began < 1
    time.sleep(1.05)
    assert not sentinel.exists()


def test_untrusted_child_output_cannot_escape_safe_result_schema(monkeypatch, tmp_path):
    monkeypatch.setattr(probe.subprocess, 'run', lambda *args, **kwargs: subprocess.CompletedProcess([], 0, b'{"status":"PASS","category":"OK","phase":"COMPLETE","token":"private"}'))
    assert probe.probe(REPOSITORY, tmp_path / 'config')['status'] == 'FAIL'


def test_network_errors_are_redacted(protocol, monkeypatch):
    def failure(*args): raise urllib.error.URLError('unit-refresh plain-unit-secret private-account')
    monkeypatch.setattr(probe, '_transport', failure)
    assert protocol['run']() == {'status': 'FAIL', 'category': 'NETWORK', 'phase': 'OAUTH_REFRESH'}
