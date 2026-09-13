"""Durable, deduplicated Pi incident delivery. Never publish provider output."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 2 * 1024 * 1024


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class DeliveryError(RuntimeError):
    """Contains only a fixed local failure category, never a response body."""


class GitHub:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise DeliveryError("INVALID_GITHUB_REPOSITORY")
        if not token or "\n" in token or "\r" in token:
            raise DeliveryError("GITHUB_TOKEN_MISSING_OR_INVALID")
        self.repository, self.token = repository, token
        self.deadline = time.monotonic() + 60
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method: str, suffix: str, value=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DeliveryError("GITHUB_DELIVERY_DEADLINE")
        # A separate short-lived process bounds DNS, headers and trickled bodies,
        # not only a socket's individual reads. Credentials travel through stdin.
        payload = {"repository": self.repository, "token": self.token,
                   "method": method, "suffix": suffix, "value": value}
        environment = {k: v for k, v in os.environ.items() if k not in {"GH_TOKEN", "GITHUB_TOKEN"}}
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-B", str(Path(__file__).absolute()), "--http-worker"],
                input=json.dumps(payload).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=min(10, remaining), env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if completed.returncode or len(completed.stdout) > MAX_BYTES * 2:
                raise DeliveryError("GITHUB_WORKER_FAILED")
            result = json.loads(completed.stdout)
            if result.get("error"):
                category = result["error"]
                if not re.fullmatch(r"GITHUB_[A-Z0-9_]{1,80}", category):
                    category = "GITHUB_WORKER_FAILED"
                raise DeliveryError(category)
            return result["value"]
        except subprocess.TimeoutExpired:
            raise DeliveryError("GITHUB_REQUEST_TIMEOUT") from None
        except (OSError, ValueError, KeyError):
            raise DeliveryError("GITHUB_WORKER_FAILED") from None

    def _request_once(self, method, suffix, value=None):
        headers = {"Authorization": "Bearer " + self.token,
                   "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "AR-local-Pi-alerts"}
        data = json.dumps(value).encode() if value is not None else None
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}/{suffix}",
            data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=10) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise DeliveryError("GITHUB_RESPONSE_TOO_LARGE")
            return json.loads(raw)
        except urllib.error.HTTPError as error:
            raise DeliveryError("GITHUB_HTTP_" + str(error.code)) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise DeliveryError("GITHUB_UNAVAILABLE_OR_INVALID_RESPONSE") from None

    def find(self, marker: str, number=None):
        if number is not None:
            row = self.request("GET", f"issues/{int(number)}")
            if marker not in str(row.get("body", "")) or "pull_request" in row:
                raise DeliveryError("GITHUB_ISSUE_IDENTITY_CHANGED")
            return row
        # Enumerate issues directly: search indexing can lag an ambiguous POST.
        # Never create if pagination cannot conclusively exclude an existing issue.
        for page in range(1, 21):
            rows = self.request("GET", f"issues?state=all&per_page=100&page={page}")
            if not isinstance(rows, list):
                raise DeliveryError("GITHUB_INVALID_ISSUE_LIST")
            found = [r for r in rows if "pull_request" not in r and marker in str(r.get("body", ""))]
            if found:
                return found[0]
            if len(rows) < 100:
                return None
        raise DeliveryError("GITHUB_ISSUE_ENUMERATION_LIMIT")


@contextlib.contextmanager
def lock(path: Path, *, wait: bool = True):
    with path.open("a+b") as stream:
        if os.name == "posix":
            import fcntl
            flags = fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB)
            fcntl.flock(stream, flags)
        else:
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"0"); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if wait else msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(stream, fcntl.LOCK_UN)
            else:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class AlertStore:
    def __init__(self, root: Path, repository="yanniedog/AR-local"):
        if not root.is_absolute() or root.resolve() != root or root.is_symlink():
            raise ValueError("unsafe alert spool")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root, self.repository = root, repository
        self.path = root / "incidents.json"

    def read(self):
        if not self.path.exists():
            return {"schema": 1, "incidents": {}}
        if self.path.is_symlink() or self.path.stat().st_size > MAX_BYTES:
            raise ValueError("unsafe alert state")
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema") != 1 or not isinstance(value.get("incidents"), dict):
            raise ValueError("invalid alert state")
        return value

    def write(self, value):
        raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
        if len(raw) > MAX_BYTES:
            raise ValueError("alert state size limit")
        fd, temporary = tempfile.mkstemp(prefix=".alerts-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            if os.name == "posix":
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(directory)
                finally: os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def observe(self, key: str, title: str, category: str, *, healthy: bool):
        if not re.fullmatch(r"[a-z0-9:-]{1,100}", key):
            raise ValueError("invalid incident key")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", category):
            raise ValueError("invalid incident category")
        if len(title) > 160 or any(c in title for c in "\r\n"):
            raise ValueError("invalid incident title")
        with lock(self.root / "state.lock"):
            state = self.read(); rows = state["incidents"]; row = rows.get(key)
            if row is None and healthy:
                return
            if row is None:
                digest = hashlib.sha256((self.repository + ":" + key).encode()).hexdigest()
                row = rows[key] = {"marker": f"<!-- ar-local-pi-incident:{digest} -->",
                                  "first_seen": utc(), "revision": 0, "delivered_revision": 0}
            changed = row.get("active") != (not healthy) or (not healthy and row.get("category") != category)
            if not changed:
                return
            row.update(title=title, active=not healthy, changed_at=utc(), revision=row["revision"] + 1)
            if healthy:
                row["recovered_at"] = utc()
            else:
                row.update(category=category, last_failure_at=utc())
            # Commit before trying GitHub, including recovery before first delivery.
            self.write(state)

    @staticmethod
    def body(row):
        return "\n".join([
            row["marker"], "", "Automatically reported by the AR-local Pi.", "",
            "State: " + ("**Needs attention**" if row["active"] else "**Recovered**"),
            "Category: `" + row["category"] + "`",
            "First observed (UTC): " + row["first_seen"],
            "Latest failure (UTC): " + row["last_failure_at"],
            "Last transition (UTC): " + row["changed_at"],
            "Last recovery (UTC): " + row.get("recovered_at", "not observed"), "",
            "This issue tracks one condition; continued failures update the same issue.",
            "Provider responses, journal output and credentials are deliberately excluded.",
            "Drive access checks do not certify a completed backup or restore.",
        ])

    def flush(self, client: GitHub):
        try:
            with lock(self.root / "delivery.lock", wait=False):
                return self._flush(client)
        except BlockingIOError:
            return {"result": "DELIVERY_ALREADY_RUNNING", "pending": True}

    def _flush(self, client):
        with lock(self.root / "state.lock"):
            pending = [(key, dict(row)) for key, row in self.read()["incidents"].items()
                       if row["revision"] != row["delivered_revision"]]
        delivered = []
        for key, row in pending:
            issue = client.find(row["marker"], row.get("issue_number"))
            value = {"title": row["title"], "body": self.body(row)}
            created = issue is None
            if issue is None:
                issue = client.request("POST", "issues", value)
            number = issue.get("number")
            if not isinstance(number, int) or number <= 0:
                raise DeliveryError("GITHUB_INVALID_CREATED_ISSUE")
            if not created or not row["active"]:
                client.request("PATCH", f"issues/{number}",
                               {**value, "state": "open" if row["active"] else "closed"})
            with lock(self.root / "state.lock"):
                state = self.read(); current = state["incidents"][key]
                current.update(issue_number=number, delivered_revision=row["revision"], delivered_at=utc())
                self.write(state)
            delivered.append(number)
        return {"result": "DELIVERED", "issues": delivered}


def configured_store() -> AlertStore:
    return AlertStore(Path(os.environ.get("AR_LOCAL_ALERT_SPOOL", "/var/lib/ar-local-alerts")),
                      os.environ.get("AR_LOCAL_ALERT_REPOSITORY", "yanniedog/AR-local"))


def deliver(store: AlertStore):
    try:
        client = GitHub(store.repository, os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", ""))
        return store.flush(client)
    except (DeliveryError, OSError, ValueError) as error:
        category = str(error) if isinstance(error, DeliveryError) else "LOCAL_DELIVERY_STATE_ERROR"
        return {"result": "QUEUED", "category": category}


if __name__ == "__main__":
    try:
        if sys.argv[1:] != ["--http-worker"]:
            raise DeliveryError("GITHUB_WORKER_ARGUMENTS")
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise DeliveryError("GITHUB_WORKER_INPUT_LIMIT")
        args = json.loads(raw)
        client = GitHub(args["repository"], args["token"])
        output = {"value": client._request_once(args["method"], args["suffix"], args.get("value"))}
    except DeliveryError as error:
        output = {"error": str(error)}
    except Exception:
        output = {"error": "GITHUB_WORKER_FAILED"}
    print(json.dumps(output), flush=True)
