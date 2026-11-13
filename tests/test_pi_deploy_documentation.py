"""Native watchdog evidence must never turn incomplete observations into health."""
import copy
import hashlib
import json
import os
import subprocess

import pytest

import pi_deploy_documentation as docs
import pi_deploy_verify as verify
from pi_deploy_service_snapshot import _snapshot_script, remote_snapshot
from tests.test_pi_deploy_verify import _verified_sync_snapshot

A, B, SITE = "a" * 40, "b" * 40, "c" * 40
DOC = "docs/PI_OPERATOR_ACCESS.md"


def tree(files):
    """Build actual Git tree-object identities, independently from API parsing."""
    entries, directories = [], {""}
    for path, mode, oid in files:
        entries.append({"path": path, "mode": mode, "type": "commit" if mode == "160000" else "blob", "sha": oid})
        parent = path.rpartition("/")[0]
        while parent:
            directories.add(parent)
            parent = parent.rpartition("/")[0]
    for directory in sorted(directories, key=len, reverse=True):
        direct = [e for e in entries if e["path"].rpartition("/")[0] == directory]
        direct.sort(key=lambda e: (e["path"].rpartition("/")[2] + ("/" if e["type"] == "tree" else "")).encode())
        body = b"".join(e["mode"].lstrip("0").encode() + b" " + e["path"].rpartition("/")[2].encode() + b"\0" + bytes.fromhex(e["sha"]) for e in direct)
        oid = hashlib.sha1(b"tree " + str(len(body)).encode() + b"\0" + body).hexdigest()
        if directory:
            entries.append({"path": directory, "mode": "040000", "type": "tree", "sha": oid})
    return {"sha": oid, "truncated": False, "tree": entries}


def evidence(after=None, before=None):
    before = tree(before or [(DOC, "100644", A), ("runtime.py", "100644", A)])
    after = tree(after or [(DOC, "100644", B), ("runtime.py", "100644", A)])
    comparison = {"base_commit": {"sha": A, "commit": {"tree": {"sha": before["sha"]}}},
                  "merge_base_commit": {"sha": A}, "status": "ahead", "ahead_by": 1,
                  "behind_by": 0, "total_commits": 1,
                  "commits": [{"sha": B, "commit": {"tree": {"sha": after["sha"]}}}]}
    replies = {f"/compare/{A}...{B}": comparison,
               f"/git/trees/{before['sha']}?recursive=1": before,
               f"/git/trees/{after['sha']}?recursive=1": after}
    return before["sha"], replies, comparison, after


def test_complete_documentation_proof_ignores_compare_files():
    local, replies, compare, _ = evidence()
    compare["files"] = [{"filename": "false-or-truncated-summary.py"}]
    assert docs.documentation_ahead(A, B, local, get=replies.__getitem__) == [DOC]


@pytest.mark.parametrize("path,mode", [("runtime.py", "100644"), ("docs/unknown.md", "100644"),
    ("docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md", "100644"), (DOC, "100755"), (DOC, "120000"),
    ("config.json", "100644"), ("module", "160000")])
def test_unknown_runtime_or_special_modes_fail(path, mode):
    local, replies, _, _ = evidence(after=[(path, mode, B), ("runtime.py", "100644", B)])
    with pytest.raises(ValueError):
        docs.documentation_ahead(A, B, local, get=replies.__getitem__)


@pytest.mark.parametrize("field,value", [("status", "diverged"), ("behind_by", 1), ("ahead_by", 251),
    ("ahead_by", True), ("total_commits", 2), ("commits", []), ("merge_base_commit", {"sha": B}),
    ("base_commit", {"sha": B}), ("commits", [{"sha": A}])])
def test_incomplete_or_nonancestor_comparison_fails(field, value):
    local, replies, compare, _ = evidence()
    compare[field] = value
    with pytest.raises(ValueError):
        docs.documentation_ahead(A, B, local, get=replies.__getitem__)


@pytest.mark.parametrize("damage", ["truncated", "missing-entry", "duplicate", "unsafe", "unknown-mode", "wrong-root", "false-hash"])
def test_tree_schema_and_complete_object_hash_enforced(damage):
    local, replies, _, after = evidence()
    if damage == "truncated": after["truncated"] = True
    if damage == "missing-entry": after["tree"].pop(0)
    if damage == "duplicate": after["tree"].append(copy.deepcopy(after["tree"][0]))
    if damage == "unsafe": after["tree"][0]["path"] = "../outside"
    if damage == "unknown-mode": after["tree"][0]["mode"] = "100664"
    if damage == "wrong-root": after["sha"] = B
    if damage == "false-hash": after["tree"][0]["sha"] = SITE
    with pytest.raises(ValueError):
        docs.documentation_ahead(A, B, local, get=replies.__getitem__)


def test_local_tree_pin_and_network_fail_closed():
    local, replies, _, _ = evidence()
    with pytest.raises(ValueError, match="local tree"):
        docs.documentation_ahead(A, B, SITE, get=replies.__getitem__)
    with pytest.raises(OSError):
        docs.documentation_ahead(A, B, local, get=lambda _: (_ for _ in ()).throw(OSError("offline")))


def snapshot(head=A):
    value = _verified_sync_snapshot(head)
    value.update(AR_HEAD_AFTER=head, SITE_HEAD=SITE, SITE_ORIGIN=SITE, SITE_HEAD_AFTER=SITE,
                 SITE_REMOTE_MAIN=SITE + "\trefs/heads/main",
                 AR_BINDING=json.dumps({"head": head, "tree": A, "clean": True}),
                 SITE_BINDING=json.dumps({"head": SITE, "tree": SITE, "clean": True}))
    return value


def prepare(monkeypatch, snap):
    calls = []
    monkeypatch.setattr(verify, "origin_main_sha_local", lambda: B)
    monkeypatch.setattr(verify, "pi_remote_snapshot", lambda **kw: calls.append(kw) or snap)
    monkeypatch.setattr(verify, "documentation_ahead", lambda *args: [DOC])
    return calls


def test_observer_accepts_proven_documentation_and_keeps_cached_refs(monkeypatch, capsys):
    snap = snapshot()
    calls = prepare(monkeypatch, snap)
    assert verify.verify_sync() == verify.EXIT_OK
    assert len(calls) == 2 and all(c["fetch"] is False for c in calls)
    assert snap["AR_ORIGIN"] == A
    assert "documentation_ahead" in capsys.readouterr().out


def test_explicit_deployment_pin_never_uses_documentation_exception(monkeypatch):
    prepare(monkeypatch, snapshot())
    monkeypatch.setattr(verify, "documentation_ahead", lambda *args: pytest.fail("pin cannot use prose proof"))
    assert verify.verify_sync(expected_commit=B) == verify.EXIT_VERIFY_FAIL


@pytest.mark.parametrize("field,value", [("AR_DIRTY", " M runtime.py"), ("AR_HEAD_AFTER", B),
    ("AR_BINDING", '{"clean":false}'), ("SITE_REMOTE_MAIN", ""), ("SITE_REMOTE_MAIN", B + "\trefs/heads/main")])
def test_bad_native_binding_stays_failure(monkeypatch, field, value):
    snap = snapshot()
    snap[field] = value
    prepare(monkeypatch, snap)
    assert verify.verify_sync() == verify.EXIT_VERIFY_FAIL


def test_moving_main_during_proof_stays_failure(monkeypatch):
    prepare(monkeypatch, snapshot())
    values = iter([B, SITE])
    monkeypatch.setattr(verify, "origin_main_sha_local", lambda: next(values))
    assert verify.verify_sync() == verify.EXIT_VERIFY_FAIL


def test_matching_live_head_ignores_stale_cached_ref_without_api(monkeypatch):
    snap = snapshot(B)
    snap["AR_ORIGIN"] = A
    prepare(monkeypatch, snap)
    monkeypatch.setattr(verify, "documentation_ahead", lambda *args: pytest.fail("no API needed"))
    assert verify.verify_sync() == verify.EXIT_OK


def test_native_snapshot_has_no_git_mutations_or_filter_operations():
    script = _snapshot_script("/srv/ar", "/srv/site", "/srv/data", "origin", fetch=False)
    for forbidden in (" fetch ", " status ", " diff ", " checkout ", " reset ", " pull "):
        assert forbidden not in script
    assert "GIT_OPTIONAL_LOCKS=0" in script
    assert "python3 -I -B -c" in script and "ls-remote --exit-code" in script


@pytest.mark.skipif(os.name == "nt", reason="Pi shell syntax is checked on POSIX")
def test_inline_snapshot_shell_syntax():
    script = _snapshot_script("/srv/ar repo", "/srv/site", "/srv/data", "origin", fetch=False)
    subprocess.run(["bash", "-n"], input=script, text=True, check=True, timeout=10)


def test_observer_does_not_require_cached_remote_refs():
    snap = snapshot()
    snap["AR_ORIGIN"] = snap["SITE_ORIGIN"] = ""
    result = remote_snapshot(ar="/ar", site="/site", data="/data", remote="origin",
                             run=lambda *a, **k: (0, "snapshot", ""), parse=lambda _: snap, fetch=False)
    assert result is snap


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        json.loads('{"sha":"a","sha":"b"}', object_pairs_hook=docs._json_unique)


@pytest.mark.parametrize("status,body,limit", [(302, b"{}", 100), (403, b"{}", 100),
    (200, b"{" + b"x" * 200, 100), (200, b'{"sha":1,"sha":2}', 100), (200, b"invalid", 100)])
def test_http_redirect_rate_schema_and_size_errors_fail(monkeypatch, status, body, limit):
    class Response:
        def read1(self, size):
            nonlocal body
            chunk, body = body[:size], body[size:]
            return chunk
    response = Response()
    response.status = status
    class Connection:
        def __init__(self, host, timeout): assert host == "api.github.com" and timeout <= 10
        def request(self, method, path, headers):
            assert method == "GET" and path.startswith(docs.API_PREFIX)
        def getresponse(self): return response
        def close(self): pass
    monkeypatch.setattr(docs.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(docs, "MAX_BYTES", limit)
    with pytest.raises(ValueError):
        docs._get("/fixed", docs.time.monotonic() + 45)


def test_expired_proof_cannot_open_connection(monkeypatch):
    monkeypatch.setattr(docs.http.client, "HTTPSConnection", lambda *a, **k: pytest.fail("expired"))
    with pytest.raises(ValueError, match="deadline"):
        docs._get("/fixed", docs.time.monotonic() - 1)


def test_existing_auth_only_sent_to_fixed_api_host(monkeypatch, capsys):
    monkeypatch.setenv("GH_TOKEN", "existing-secret")
    assert docs._token() == "existing-secret"
    body = b"{}"
    class Connection:
        status = 200
        def __init__(self, host, timeout): assert host == "api.github.com"
        def request(self, method, path, headers): assert headers["Authorization"] == "Bearer existing-secret"
        def getresponse(self): return self
        def read1(self, size):
            nonlocal body
            chunk, body = body, b""
            return chunk
        def close(self): pass
    monkeypatch.setattr(docs.http.client, "HTTPSConnection", Connection)
    assert docs._get("/fixed", docs.time.monotonic() + 45, docs._token()) == {}
    assert "existing-secret" not in str(capsys.readouterr())


def test_service_change_during_documentation_proof_fails(monkeypatch):
    first, second = snapshot(), snapshot()
    second["DASHBOARD"] = "inactive"
    prepare(monkeypatch, first)
    values = iter([first, second])
    monkeypatch.setattr(verify, "pi_remote_snapshot", lambda **kw: next(values))
    assert verify.verify_sync() == verify.EXIT_VERIFY_FAIL
