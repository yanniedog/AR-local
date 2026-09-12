"""Bounded GitHub release I/O for immutable v1 archives, never pruning assets.

The Pi is the single publication writer. Callers hold the production operation
lock (and the revision coordinator also holds its own crash-recoverable lock).
GitHub release asset replacement has no CAS: check the complete predecessor
immediately before replacement and verify exact public bytes afterwards. A
second publishing host must use the same coordinator/lock, not this low-level
backend directly.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from ar_local_backup_policy import fsync_directory
from app_payload_revisions_state import (
    MAX_ASSET_BYTES, MAX_DOCUMENT_BYTES, RevisionError, digest,
)
from pi_payload_freshness import fresh_document_url


def write_once(path: Path, raw: bytes) -> None:
    """Atomic immutable creation, safe to retry after an interrupted staging write."""
    if path.exists():
        if path.read_bytes() != raw:
            raise RevisionError(f"immutable local bytes differ: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.urandom(8).hex()}.partial")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # All writers hold the coordinator lock; no replacing a pre-existing file.
        if path.exists():
            raise RevisionError("immutable staging destination appeared concurrently")
        temporary.rename(path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class _GitHubRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        parsed = urllib.parse.urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or not ((parsed.hostname or "") == "github.com"
                        or (parsed.hostname or "").endswith(".githubusercontent.com"))):
            raise RevisionError("public asset redirect left GitHub HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GitHubRevisionStore:
    def __init__(self, repo: str, gh: str | None = None) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise RevisionError("invalid GitHub repository")
        self.repo = repo
        self.gh = gh or shutil.which("gh")
        if not self.gh:
            raise RevisionError("GitHub CLI is required for revision publication")

    def url(self, tag: str, name: str) -> str:
        return f"https://github.com/{self.repo}/releases/download/{tag}/{name}"

    def _run(self, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        # nosemgrep: dangerous-subprocess-use-audit - fixed argv, no shell.
        result = subprocess.run([self.gh, *args], shell=False, capture_output=True,
                                text=True, timeout=300)
        if check and result.returncode:
            # CLI diagnostics may contain account-specific information; keep bounded.
            raise RevisionError(f"GitHub {args[0]} failed (exit={result.returncode})")
        return result

    def read(self, tag: str, name: str, limit: int = MAX_DOCUMENT_BYTES) -> bytes | None:
        return self.read_url(self.url(tag, name), limit)

    def read_url(self, url: str, limit: int = MAX_ASSET_BYTES) -> bytes | None:
        parsed = urllib.parse.urlsplit(url)
        expected = f"/{self.repo}/releases/download/"
        if (parsed.scheme != "https" or parsed.netloc != "github.com"
                or not parsed.path.startswith(expected) or parsed.query or parsed.fragment
                or limit <= 0 or limit > MAX_ASSET_BYTES):
            raise RevisionError("invalid public revision asset URL or byte budget")
        # GitHub caches release-asset redirects, including a replaced index and
        # the initial 404 of an in-progress archive. Exact readback must bypass it.
        request = urllib.request.Request(fresh_document_url(url), headers={
            "Accept-Encoding": "identity", "Cache-Control": "no-cache",
        })
        try:
            opener = urllib.request.build_opener(_GitHubRedirect())
            with opener.open(request, timeout=60) as response:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > limit:
                    raise RevisionError("public response exceeds byte budget")
                raw = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise RevisionError(f"public download failed with HTTP {exc.code}") from exc
        if len(raw) > limit:
            raise RevisionError("public response exceeds byte budget")
        return raw

    def tags(self) -> list[str]:
        result = self._run(["api", "--paginate", f"repos/{self.repo}/releases?per_page=100",
                            "--jq", ".[].tag_name"])
        return result.stdout.splitlines()

    def ensure_release(self, tag: str) -> None:
        result = self._run(["api", f"repos/{self.repo}/releases/tags/{tag}"], check=False)
        if result.returncode == 0:
            return
        if "HTTP 404" not in result.stderr:
            raise RevisionError("cannot distinguish missing release from GitHub failure")
        self._run(["release", "create", tag, "--repo", self.repo,
                   "--title", tag, "--notes", "Preserved mobile payload revision and audit evidence.",
                   "--latest=false"])

    def archive(self, tag: str, paths: list[Path]) -> None:
        self.ensure_release(tag)
        for path in paths:
            local = path.read_bytes()
            remote = self.read(tag, path.name, max(len(local), 1))
            if remote is not None:
                if remote != local:
                    raise RevisionError(f"immutable release collision: {tag}/{path.name}")
                continue
            try:
                self._run(["release", "upload", tag, str(path), "--repo", self.repo])
            except (RevisionError, subprocess.SubprocessError):
                # A timed-out upload may have completed. Never clobber immutable
                # bytes; accept only independently downloaded byte equality.
                if self.read(tag, path.name, max(len(local), 1)) == local:
                    continue
                raise
            verified = self.read(tag, path.name, max(len(local), 1))
            if verified != local:
                raise RevisionError(f"public archive verification failed: {tag}/{path.name}")

    def replace_index(self, tag: str, path: Path, expected: bytes | None) -> None:
        if expected is None:
            self.ensure_release(tag)
        current = self.read(tag, "dates-index.json")
        if current != expected:
            raise RevisionError("stale publisher: dates-index predecessor changed")
        try:
            self._run(["release", "upload", tag, str(path), "--repo", self.repo, "--clobber"])
        except (RevisionError, subprocess.SubprocessError):
            # An uncertain successful upload is success only after exact readback.
            observed = self.read(tag, "dates-index.json")
            if observed == path.read_bytes():
                return
            if observed is None and expected is not None:
                recovery = path.parent / "restore" / "dates-index.json"
                write_once(recovery, expected)
                self._run(["release", "upload", tag, str(recovery), "--repo", self.repo])
            raise
        if self.read(tag, "dates-index.json") != path.read_bytes():
            raise RevisionError("selected revision index failed public byte verification")

    def restore_missing_index(self, tag: str, path: Path) -> None:
        """Restore an interrupted replacement without overwriting another writer."""
        expected = path.read_bytes()
        observed = self.read(tag, "dates-index.json")
        if observed == expected:
            return
        if observed is not None:
            raise RevisionError("index appeared before interrupted-promotion recovery")
        try:
            self._run(["release", "upload", tag, str(path), "--repo", self.repo])
        except (RevisionError, subprocess.SubprocessError):
            if self.read(tag, "dates-index.json") == expected:
                return
            raise
        if self.read(tag, "dates-index.json") != expected:
            raise RevisionError("restored revision index failed public byte verification")


def download_manifest_assets(
    store: Any, manifest: dict[str, Any], destination: Path,
) -> None:
    for entry in manifest["files"].values():
        raw = store.read_url(entry["url"], entry["bytes"])
        if raw is None or len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
            raise RevisionError(f"source asset fails hash verification: {entry['name']}")
        write_once(destination / entry["name"], raw)
