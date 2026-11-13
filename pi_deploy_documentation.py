"""Fail-closed documentation equivalence for the native observation-only watchdog."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import subprocess
import time

SHA = re.compile(r"[0-9a-f]{40}\Z")
API_PREFIX = "/repos/yanniedog/AR-local"
MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 100_000
# Explicitly reviewed operator prose. Unknown Markdown is not presumed inert.
DOCUMENTATION = frozenset({
    "docs/INGEST_RESILIENCE_REPAIR_20261113.md",
    "docs/INGEST_RESILIENCE_OPERATIONS_20261113.md",
    "docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md",
    "docs/PI_MAINTENANCE_WINDOW.md",
    "docs/PI_OPERATOR_ACCESS.md",
})


def _sha(value):
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("invalid Git object identity")
    return value


def _json_unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _get(path, deadline, token=None):
    """Fixed public endpoint, existing auth only, no redirects; bounded bytes/time."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("GitHub evidence deadline exceeded")
    connection = http.client.HTTPSConnection("api.github.com", timeout=min(10, remaining))
    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ar-local-native-watchdog/1",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        connection.request("GET", API_PREFIX + path, headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"GitHub evidence HTTP {response.status}")
        body = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise ValueError("GitHub evidence deadline exceeded")
            chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError("GitHub evidence exceeds byte bound")
        return json.loads(body.decode("utf-8"), object_pairs_hook=_json_unique)
    finally:
        connection.close()


def _token():
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                    capture_output=True, timeout=5, check=True)
            token = result.stdout.decode("ascii").strip()
        except (OSError, UnicodeError, subprocess.SubprocessError):
            return None
    if not token.isascii() or any(c.isspace() for c in token) or len(token) > 4096:
        raise ValueError("invalid existing GitHub authentication")
    return token


def _tree(value, expected):
    """Reconstruct every Git tree object; a missing entry cannot appear complete."""
    if not isinstance(value, dict) or value.get("sha") != expected or value.get("truncated") is not False:
        raise ValueError("incomplete or mismatched Git tree")
    entries = value.get("tree")
    if not isinstance(entries, list) or not 0 < len(entries) <= MAX_ENTRIES:
        raise ValueError("invalid tree entry count")
    nodes, children = {}, {"": []}
    kinds = {"040000": "tree", "100644": "blob", "100755": "blob", "120000": "blob", "160000": "commit"}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid tree entry")
        path, mode, kind = entry.get("path"), entry.get("mode"), entry.get("type")
        if (not isinstance(path, str) or not path or path in nodes or "\\" in path
                or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or any(p in {"", ".", ".."} for p in path.split("/"))
                or mode not in kinds or kinds[mode] != kind):
            raise ValueError("unsafe or unknown tree entry")
        oid = _sha(entry.get("sha"))
        nodes[path] = (mode, kind, oid)
        parent, _, name = path.rpartition("/")
        children.setdefault(parent, []).append((name, mode, oid))
        if kind == "tree":
            children.setdefault(path, [])
    for directory, items in children.items():
        if directory and (directory not in nodes or nodes[directory][1] != "tree"):
            raise ValueError("missing parent directory")
        items.sort(key=lambda item: (item[0] + ("/" if item[1] == "040000" else "")).encode("utf-8"))
        body = b"".join(mode.lstrip("0").encode() + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(oid)
                        for name, mode, oid in items)
        digest = hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
        if digest != (nodes[directory][2] if directory else expected):
            raise ValueError("Git tree content identity mismatch")
    return nodes


def documentation_ahead(deployed, main, local_tree, *, get=None):
    """Return changed approved prose paths, or raise; never authorize deployment."""
    deployed, main, local_tree = map(_sha, (deployed, main, local_tree))
    deadline = time.monotonic() + 45
    if get is None:
        token = _token()
        get = lambda path: _get(path, deadline, token)
    comparison = get(f"/compare/{deployed}...{main}")
    if not isinstance(comparison, dict):
        raise ValueError("invalid comparison")
    base, merge, commits = (comparison.get(k) for k in ("base_commit", "merge_base_commit", "commits"))
    ahead, total = comparison.get("ahead_by"), comparison.get("total_commits")
    if (not isinstance(base, dict) or base.get("sha") != deployed
            or not isinstance(merge, dict) or merge.get("sha") != deployed
            or comparison.get("status") != "ahead" or type(comparison.get("behind_by")) is not int or comparison["behind_by"] != 0
            or type(ahead) is not int or not 0 < ahead <= 250 or type(total) is not int or total != ahead
            or not isinstance(commits, list) or len(commits) != ahead
            or any(not isinstance(c, dict) or not SHA.fullmatch(str(c.get("sha", ""))) for c in commits)
            or len({c["sha"] for c in commits}) != ahead or commits[-1]["sha"] != main):
        raise ValueError("comparison is incomplete or not a fast-forward")
    try:
        base_tree = _sha(base["commit"]["tree"]["sha"])
        main_tree = _sha(commits[-1]["commit"]["tree"]["sha"])
    except (KeyError, TypeError) as exc:
        raise ValueError("missing commit tree identity") from exc
    if base_tree != local_tree:
        raise ValueError("deployed local tree differs from GitHub commit")
    before = _tree(get(f"/git/trees/{base_tree}?recursive=1"), base_tree)
    after = _tree(get(f"/git/trees/{main_tree}?recursive=1"), main_tree)
    differences = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    changed = sorted(path for path in differences
                     if any(facts and facts[1] != "tree" for facts in (before.get(path), after.get(path))))
    for path in changed:
        if path not in DOCUMENTATION or any(facts and facts[:2] != ("100644", "blob") for facts in (before.get(path), after.get(path))):
            raise ValueError(f"runtime or unknown path differs: {path}")
    if any(not any(leaf.startswith(path + "/") for leaf in changed) for path in differences - set(changed)):
        raise ValueError("unexplained directory difference")
    return changed


def native_binding(snap):
    """Require successful, unmasked clean-index reads and stable checkout identity."""
    for prefix in ("AR", "SITE"):
        head = _sha(snap.get(prefix + "_HEAD"))
        value = json.loads(snap.get(prefix + "_BINDING", "null"), object_pairs_hook=_json_unique)
        if (not isinstance(value, dict) or set(value) != {"head", "tree", "clean"}
                or value.get("clean") is not True or value.get("head") != head
                or snap.get(prefix + "_HEAD_AFTER") != head or snap.get(prefix + "_DIRTY") != ""):
            raise ValueError(f"{prefix} checkout dirty, raced or unreadable")
        _sha(value.get("tree"))
        if prefix == "AR":
            ar_tree = value["tree"]
    site_ref = snap.get("SITE_REMOTE_MAIN", "").split()
    if len(site_ref) != 2 or site_ref[1] != "refs/heads/main" or _sha(site_ref[0]) != snap["SITE_HEAD"]:
        raise ValueError("site HEAD differs from live remote main")
    return snap["AR_HEAD"], ar_tree, snap["SITE_HEAD"], snap["SITE_REMOTE_MAIN"]
