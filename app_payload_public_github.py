"""Atomic app-only Git data branch; encrypted release egress stays unchanged."""
from __future__ import annotations

import base64
import json
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from app_payload_revisions_state import RevisionError
from app_payload_secure_upload import ASSET
from pi_payload_freshness import fresh_document_url

BRANCH = "app-payload-public"
TAG = re.compile(r"app-payload-[0-9]{4}-[0-9]{2}-[0-9]{2}-r[0-9]{6}")


def public_asset(name: str) -> bool:
    return name == "manifest.json" or bool(ASSET.fullmatch(name) and not name.endswith(".enc"))


def public_path(path: str) -> bool:
    if path in {"latest/manifest.json", "latest/dates-index.json"}:
        return True
    parts = path.split("/")
    return len(parts) == 3 and parts[0] == "tags" and bool(TAG.fullmatch(parts[1])) and public_asset(parts[2])


class PublicGitHubStore:
    def __init__(self, repo: str, *, gh="gh"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise RevisionError("Invalid public data repository")
        self.repo, self.gh = repo, gh

    def api(self, method, path, body=None, *, missing=False):
        command = [self.gh, "api", "--method", method, f"repos/{self.repo}/{path}"]
        with tempfile.TemporaryDirectory(prefix="ar-public-git-") as temporary:
            if body is not None:
                source = Path(temporary) / "request.json"
                source.write_text(json.dumps(body), encoding="utf-8")
                command += ["--input", str(source)]
            result = subprocess.run(command, shell=False, capture_output=True, text=True, timeout=120)
        if result.returncode:
            if missing and "HTTP 404" in result.stderr:
                return None
            raise RevisionError(f"Public GitHub {method} failed (exit={result.returncode})")
        return json.loads(result.stdout)

    def head(self):
        value = self.api("GET", f"git/ref/heads/{BRANCH}", missing=True)
        return value["object"]["sha"] if value else None

    def read(self, ref: str, path: str, limit: int):
        if not public_path(path) or not (ref == BRANCH or re.fullmatch(r"[a-f0-9]{40}", ref)):
            raise RevisionError("Public raw read is outside the app inventory")
        url = f"https://raw.githubusercontent.com/{self.repo}/{ref}/{path}"
        request = urllib.request.Request(fresh_document_url(url), headers={"Accept-Encoding": "identity", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read(limit + 1)
        if len(raw) > limit or raw.startswith((b"ARE1", b"ARE2")):
            raise RevisionError("Public raw bytes exceed or violate the readable receipt")
        return raw

    def snapshot(self):
        head = self.head()
        if head is None:
            return None, None, {}
        tree = self.api("GET", f"git/commits/{head}")["tree"]["sha"]
        value = self.api("GET", f"git/trees/{tree}?recursive=1")
        if value.get("truncated"):
            raise RevisionError("Public branch inventory is incomplete")
        entries = {}
        for row in value["tree"]:
            if row["type"] == "tree":
                continue
            if row["type"] != "blob" or row["mode"] != "100644" or not public_path(row["path"]):
                raise RevisionError("Public branch contains an unrecognized object")
            entries[row["path"]] = row["sha"]
        return head, tree, entries

    def stage(self, head, base_tree, files):
        entries = []
        for path, raw in files.items():
            if not public_path(path) or raw.startswith((b"ARE1", b"ARE2")):
                raise RevisionError("Private or encrypted object cannot enter the public branch")
            blob = self.api("POST", "git/blobs", {"content": base64.b64encode(raw).decode("ascii"), "encoding": "base64"})
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        body = {"tree": entries}
        if base_tree:
            body["base_tree"] = base_tree
        tree = self.api("POST", "git/trees", body)
        commit = self.api("POST", "git/commits", {"message": "Publish verified app data", "tree": tree["sha"], "parents": [head] if head else []})
        return commit["sha"]

    def promote(self, previous, commit):
        if self.head() != previous:
            raise RevisionError("Public branch predecessor changed")
        try:
            if previous:
                self.api("PATCH", f"git/refs/heads/{BRANCH}", {"sha": commit, "force": False})
            else:
                self.api("POST", "git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": commit})
        except RevisionError:
            if self.head() != commit:
                raise
        if self.head() != commit:
            raise RevisionError("Public branch promotion is unconfirmed")
