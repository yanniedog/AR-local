"""Bounded, read-only Google access checks; never backup or restore acceptance.

The only public output is status/category/phase. Credentials stay in the private
config and HTTP form/header, never argv, diagnostics or returned provider text.
The isolated worker makes whole-probe cancellation cover DNS, headers and reads.
"""
from __future__ import annotations

import configparser
import http.client
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TOTAL_SECONDS = 60
HTTP_SECONDS = 10
MAX_BYTES = 1024 * 1024
MAX_PAGES = 3
SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_URL = "https://www.googleapis.com/drive/v3/"
FOLDER = "application/vnd.google-apps.folder"
CATEGORIES = frozenset({"OK", "CONFIG_MISSING", "CONFIG_INVALID", "CONFIG_PERMISSIONS", "CLIENT_MISSING",
    "GRANT_MISSING", "SCOPE_INVALID", "AUTH_REVOKED", "AUTH_CLIENT", "AUTHORIZATION", "PERMISSION",
    "WRITE_DENIED", "READ_DENIED", "REPOSITORY_MISSING", "REPOSITORY_AMBIGUOUS", "STORAGE_QUOTA",
    "API_RATE_LIMIT", "API_DISABLED", "API_ERROR", "NETWORK", "TIMEOUT", "REDIRECT_REFUSED",
    "RESPONSE_INVALID", "LIMIT_EXCEEDED", "UNKNOWN"})
PHASES = frozenset({"CONFIG", "OAUTH_REFRESH", "QUOTA", "REPOSITORY", "FOLDER_ACCESS",
                    "CONFIG_OBJECT", "CONFIG_DOWNLOAD", "COMPLETE", "PROBE"})


class _Failure(Exception):
    pass


def _require(value, category="RESPONSE_INVALID"):
    if not value:
        raise _Failure(category)


def _result(category, phase):
    return {"status": "PASS" if category == "OK" else "FAIL", "category": category, "phase": phase}


def _json(raw):
    def number(value):
        _require(len(value) <= 32)
        return int(value)
    return json.loads(raw, parse_int=number, parse_constant=lambda _: _require(False))


def _repository(value):
    _require(isinstance(value, str) and len(value) <= 4096, "CONFIG_INVALID")
    match = re.fullmatch(r"rclone:([A-Za-z0-9_-]{1,64}):([^\r\n\x00]+)", value)
    _require(match is not None, "CONFIG_INVALID")
    parts = match[2].split("/")
    _require(all(p and p not in {".", ".."} and len(p) <= 1024
                 and not any(ord(c) < 32 for c in p) for p in parts), "CONFIG_INVALID")
    _require(len(parts) <= 16, "LIMIT_EXCEEDED")
    return match[1], parts


def _read_private(path):
    _require(os.name == "posix", "CONFIG_PERMISSIONS")  # No Windows ACL claim.
    try:
        _require(path.is_absolute() and path.resolve(strict=True) == path and not path.is_symlink(), "CONFIG_PERMISSIONS")
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            info = os.fstat(stream.fileno())
            _require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600
                     and (os.getuid() == 0 or info.st_uid == os.getuid()), "CONFIG_PERMISSIONS")
            _require(info.st_size <= MAX_BYTES, "LIMIT_EXCEEDED")
            raw = stream.read(MAX_BYTES + 1)
        _require(len(raw) <= MAX_BYTES, "LIMIT_EXCEEDED")
        return raw
    except FileNotFoundError:
        raise _Failure("CONFIG_MISSING") from None
    except (PermissionError, OSError):
        raise _Failure("CONFIG_PERMISSIONS") from None


def _credentials(raw, remote):
    try:
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(raw.decode("utf-8"))
        _require(not config.defaults() and remote in config, "CONFIG_INVALID")
        value = config[remote]
        _require(value.get("type") == "drive", "CONFIG_INVALID")
        _require(value.get("scope") == "drive.file", "SCOPE_INVALID")
        # Reject settings that would make the direct API resolve a different tree.
        for key in ("team_drive", "service_account_file", "service_account_credentials", "impersonate",
                    "shared_with_me", "trashed_only", "auth_url", "token_url", "encoding"):
            _require(not value.get(key), "CONFIG_INVALID")
        client, secret = value.get("client_id", ""), value.get("client_secret", "")
        _require(re.fullmatch(r"[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com", client)
                 and 1 <= len(secret) <= 2048 and not any(c.isspace() for c in secret), "CLIENT_MISSING")
        token = _json(value.get("token", "{}"))
        refresh = token.get("refresh_token") if isinstance(token, dict) else None
        _require(isinstance(refresh, str) and 0 < len(refresh) <= 16384
                 and not any(c.isspace() for c in refresh), "GRANT_MISSING")
        root = value.get("root_folder_id") or "root"
        _require(re.fullmatch(r"[A-Za-z0-9_-]{1,256}", root), "CONFIG_INVALID")
        return client, secret, refresh, root
    except (configparser.Error, UnicodeError, ValueError, TypeError):
        raise _Failure("CONFIG_INVALID") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _body(response):
    length = response.headers.get("Content-Length")
    if length is not None:
        _require(length.isascii() and length.isdecimal() and len(length) <= 12)
        length = int(length)
        _require(length <= MAX_BYTES, "LIMIT_EXCEEDED")
    _require(response.headers.get("Content-Encoding", "identity").lower() == "identity")
    raw = response.read(MAX_BYTES + 1)
    _require(len(raw) <= MAX_BYTES, "LIMIT_EXCEEDED")
    _require(length is None or len(raw) == length)
    return raw


def _transport(request, seconds):
    # No inherited proxies, auth handlers, retries or credential-bearing redirects.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        response = opener.open(request, timeout=seconds)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.code, _body(response)


def _http(request, deadline):
    seconds = min(HTTP_SECONDS, deadline - time.monotonic())
    _require(seconds > 0, "TIMEOUT")
    box = []
    def transfer():
        try:
            box.append(_transport(request, seconds))
        except Exception as error:
            box.append(error)
    thread = threading.Thread(target=transfer, daemon=True)
    thread.start(); thread.join(seconds)
    # On timeout the worker returns immediately and exits, ending the daemon I/O
    # thread. No further requests run with an outstanding timed-out transfer.
    _require(not thread.is_alive(), "TIMEOUT")
    item = box[0]
    if isinstance(item, _Failure):
        raise item
    if isinstance(item, (TimeoutError, socket.timeout)):
        raise _Failure("TIMEOUT")
    if isinstance(item, urllib.error.URLError):
        raise _Failure("TIMEOUT" if isinstance(item.reason, (TimeoutError, socket.timeout)) else "NETWORK")
    if isinstance(item, (OSError, http.client.HTTPException)):
        raise _Failure("NETWORK")
    if isinstance(item, Exception):
        raise _Failure("UNKNOWN")
    return item


def _error(status, raw):
    if 300 <= status < 400:
        return "REDIRECT_REFUSED"
    reasons = set()
    try:
        body = _json(raw).get("error")
        if isinstance(body, str):
            reasons.add(body)
        elif isinstance(body, dict):
            reasons.update(item.get("reason") for item in body.get("errors", []) if isinstance(item, dict)
                           and isinstance(item.get("reason"), str))
    except (ValueError, TypeError, AttributeError, _Failure):
        pass
    for names, category in (({"invalid_grant"}, "AUTH_REVOKED"), ({"invalid_client", "unauthorized_client"}, "AUTH_CLIENT"),
            ({"invalid_scope"}, "SCOPE_INVALID"), ({"storageQuotaExceeded"}, "STORAGE_QUOTA"),
            ({"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded"}, "API_RATE_LIMIT"),
            ({"accessNotConfigured", "serviceDisabled"}, "API_DISABLED")):
        if reasons & names:
            return category
    return {401: "AUTHORIZATION", 403: "PERMISSION", 404: "REPOSITORY_MISSING", 429: "API_RATE_LIMIT"}.get(status, "API_ERROR")


class _Client:
    def __init__(self, deadline):
        self.deadline, self.token = deadline, None

    def request(self, path=None, *, query=None, form=None, media=False):
        if form is not None:
            url, data = TOKEN_URL, urllib.parse.urlencode(form).encode("ascii")
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
        else:
            _require(isinstance(path, str) and re.fullmatch(r"(?:about|files(?:/[A-Za-z0-9_-]{1,256})?)", path))
            url, data = DRIVE_URL + path, None
            headers = {"Authorization": "Bearer " + self.token}
        if query:
            url += "?" + urllib.parse.urlencode(query)
        headers["Accept-Encoding"] = "identity"
        status, raw = _http(urllib.request.Request(url, data=data, headers=headers), self.deadline)
        _require(status == 200, _error(status, raw))
        if media:
            return raw
        try:
            result = _json(raw)
        except (ValueError, TypeError, _Failure):
            raise _Failure("RESPONSE_INVALID") from None
        _require(isinstance(result, dict))
        return result


def _escape(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _child(client, parent, name, *, folder):
    kind = "=" if folder else "!="
    query = {"q": f"'{_escape(parent)}' in parents and name = '{_escape(name)}' and trashed = false and mimeType {kind} '{FOLDER}'",
             "fields": "nextPageToken,incompleteSearch,files(id,name,mimeType,trashed)", "pageSize": "100", "spaces": "drive"}
    matches, tokens = [], set()
    for _ in range(MAX_PAGES):
        page = client.request("files", query=query)
        _require(page.get("incompleteSearch", False) is False, "LIMIT_EXCEEDED")
        rows = page.get("files")
        _require(isinstance(rows, list) and len(rows) <= 100)
        for row in rows:
            _require(isinstance(row, dict) and row.get("name") == name and row.get("trashed") is False
                     and isinstance(row.get("mimeType"), str) and (row["mimeType"] == FOLDER) == folder
                     and isinstance(row.get("id"), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", row["id"]))
            matches.append(row["id"])
        _require(len(matches) <= 1, "REPOSITORY_AMBIGUOUS")
        token = page.get("nextPageToken")
        if token is None:
            _require(len(matches) == 1, "REPOSITORY_MISSING")
            return matches[0]
        _require(isinstance(token, str) and 0 < len(token) <= 4096 and token not in tokens)
        tokens.add(token); query["pageToken"] = token
    raise _Failure("LIMIT_EXCEEDED")


def _integer_string(value):
    _require(isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 24)
    return int(value)


def _run(repository, path):
    phase = "CONFIG"
    try:
        deadline = time.monotonic() + TOTAL_SECONDS - 1
        remote, parts = _repository(repository)
        client_id, secret, refresh, parent = _credentials(_read_private(path), remote)
        client = _Client(deadline)
        phase = "OAUTH_REFRESH"
        token = client.request(form={"client_id": client_id, "client_secret": secret,
                                     "refresh_token": refresh, "grant_type": "refresh_token"})
        access = token.get("access_token")
        _require(isinstance(access, str) and 0 < len(access) <= 16384 and not any(c.isspace() for c in access)
                 and token.get("token_type", "").lower() == "bearer" and type(token.get("expires_in")) is int and token["expires_in"] > 0)
        _require("scope" not in token or token["scope"] == SCOPE, "SCOPE_INVALID")
        client.token = access
        phase = "QUOTA"
        quota = client.request("about", query={"fields": "storageQuota"}).get("storageQuota")
        _require(isinstance(quota, dict))
        used = _integer_string(quota.get("usage"))
        if "limit" in quota:
            _require(used < _integer_string(quota["limit"]), "STORAGE_QUOTA")
        phase = "REPOSITORY"
        for name in parts:
            parent = _child(client, parent, name, folder=True)
        phase = "FOLDER_ACCESS"
        folder = client.request("files/" + parent, query={"fields": "id,mimeType,trashed,capabilities(canAddChildren)"})
        _require(folder.get("id") == parent and folder.get("mimeType") == FOLDER and folder.get("trashed") is False)
        _require(folder.get("capabilities", {}).get("canAddChildren") is True, "WRITE_DENIED")
        phase = "CONFIG_OBJECT"
        file_id = _child(client, parent, "config", folder=False)
        file = client.request("files/" + file_id, query={"fields": "id,name,mimeType,trashed,size,capabilities(canDownload)"})
        _require(file.get("id") == file_id and file.get("name") == "config" and file.get("mimeType") != FOLDER and file.get("trashed") is False)
        _require(file.get("capabilities", {}).get("canDownload") is True, "READ_DENIED")
        size = _integer_string(file.get("size"))
        _require(0 < size <= MAX_BYTES, "LIMIT_EXCEEDED")
        phase = "CONFIG_DOWNLOAD"
        raw = client.request("files/" + file_id, query={"alt": "media"}, media=True)
        _require(len(raw) == size and size > 0)
        _require(time.monotonic() < deadline, "TIMEOUT")
        return _result("OK", "COMPLETE")
    except _Failure as error:
        return _result(error.args[0] if error.args and error.args[0] in CATEGORIES else "UNKNOWN", phase)
    except Exception:
        return _result("UNKNOWN", phase)


def probe(repository: str, rclone_config: Path) -> dict:
    """Check actual read/write capabilities without writing Drive or credentials.

    PASS proves this bounded access probe only, never a verified backup/restore.
    Total timeout kills and waits for the isolated worker with native platform
    termination. Its HTTP threads are daemon threads; there are no grandchildren.
    """
    deadline = time.monotonic() + TOTAL_SECONDS
    try:
        _repository(repository)
        _require(isinstance(rclone_config, Path) and len(str(rclone_config)) <= 4096, "CONFIG_INVALID")
        payload = json.dumps({"repository": repository, "config": str(rclone_config)}).encode()
        _require(len(payload) <= 32768, "LIMIT_EXCEEDED")
        completed = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).absolute()), "--worker"],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
            timeout=max(0.01, deadline - time.monotonic()), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _require(completed.returncode == 0 and len(completed.stdout) <= 1024, "UNKNOWN")
        result = json.loads(completed.stdout)
        _require(isinstance(result, dict) and set(result) == {"status", "category", "phase"}
                 and result["category"] in CATEGORIES and result["phase"] in PHASES
                 and result["status"] == ("PASS" if result["category"] == "OK" else "FAIL"), "UNKNOWN")
        return result
    except subprocess.TimeoutExpired:
        return _result("TIMEOUT", "PROBE")
    except _Failure as error:
        return _result(error.args[0], "CONFIG")
    except Exception:
        return _result("UNKNOWN", "PROBE")


if __name__ == "__main__":
    try:
        _require(sys.argv[1:] == ["--worker"])
        payload = sys.stdin.buffer.read(32769)
        _require(len(payload) <= 32768)
        args = _json(payload)
        outcome = _run(args["repository"], Path(args["config"]))
    except Exception:
        outcome = _result("CONFIG_INVALID", "CONFIG")
    print(json.dumps(outcome, sort_keys=True), flush=True)
