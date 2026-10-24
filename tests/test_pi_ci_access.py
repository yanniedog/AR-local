"""Adversarial protocol and privilege-boundary tests; no Pi or sudo execution."""
import hashlib
import json
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import pi_ci_access as ci


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def approved_plan(monkeypatch):
    now = datetime(2026, 10, 24, 3, tzinfo=timezone.utc)
    proofs = {name: encoded({"retained_receipt": name}) for name in
              ("raw_archive", "system_image", "restore_proof", "boot_structure_proof")}
    recovery = encoded({"schema_version": 1, "result": "PASS", "evidence": {
        name: {"path": "/root/recovery/" + name + ".json", "sha256": digest(body)}
        for name, body in proofs.items()}})
    manifest = encoded({"schema": "actual-sealed-manifest-validated-by-adapter"})
    adapter = b"# independently reviewed privilege-separated adapter\n"
    plan = {"schema_version": 1, "scope": "activate-sealed-d027", "target_commit": "a" * 40,
            "previous_commit": "b" * 40, "expires_at": (now + timedelta(hours=2)).isoformat(),
            "sealed_manifest_sha256": digest(manifest), "recovery_approval_sha256": digest(recovery),
            "adapter_sha256": digest(adapter)}
    files = {ci.ADAPTER: adapter, **{Path("/root/recovery/" + name + ".json"): body
                                    for name, body in proofs.items()}}

    def install(value):
        body = encoded(value)
        plan_id = digest(body)
        files.update({ci.PLANS / (plan_id + ".json"): body,
                      ci.PLANS / (plan_id + ".activation.json"): manifest,
                      ci.PLANS / (plan_id + ".recovery.json"): recovery})
        return plan_id

    monkeypatch.setattr(ci, "trusted_bytes", lambda path, **kwargs: files[path])
    return plan, now, files, install


def test_only_exact_protocol_commands():
    assert ci.parse_command("status") == {"action": "status"}
    assert ci.parse_command("activate " + "a" * 64) == {"action": "activate", "plan": "a" * 64}


@pytest.mark.parametrize("command", ["", " status", "status\n", "status; id", "status && id",
    "$(id)", "`id`", "bash", "sh -c status", "sudo -n sh", "scp -t /tmp/x", "sftp", "env",
    "activate ../etc/passwd", "activate " + "a" * 40, "activate " + "A" * 64,
    "activate " + "a" * 64 + "\n", "activate " + "a" * 64 + " --source /tmp/x"])
def test_reject_shell_expansion_paths_and_file_transfer(command):
    with pytest.raises(ValueError):
        ci.parse_command(command)


@pytest.mark.parametrize("value", [None, [], True, {"action": "status", "command": "id"},
    {"action": "activate", "plan": 1}, {"action": "activate", "plan": "../x"},
    {"action": "activate", "plan": "a" * 64, "env": {"PYTHONPATH": "/tmp"}}])
def test_json_cannot_supply_paths_commands_or_environment(value):
    with pytest.raises(ValueError):
        ci.request_from_json(json.dumps(value))


def test_plan_binds_manifest_recovery_receipts_and_fixed_adapter(monkeypatch):
    plan, now, files, install = approved_plan(monkeypatch)
    plan_id = install(plan)
    assert ci.validate_plan(plan_id, now=now) == plan
    files[ci.ADAPTER] = b"modified adapter"
    with pytest.raises(ValueError, match="digest differs"):
        ci.validate_plan(plan_id, now=now)


@pytest.mark.parametrize("mutation", [
    {"scope": "root-shell"}, {"source": "/tmp/attacker"}, {"target_commit": "main"},
    {"expires_at": "2026-10-24T03:00:00+00:00"}, {"expires_at": "2026-10-24T03:15:00+00:00"},
    {"expires_at": "2026-10-25T03:00:00+00:00"}, {"expires_at": "2026-10-24T05:00:00"},
])
def test_plan_rejects_expiry_broad_scope_and_arbitrary_source(monkeypatch, mutation):
    plan, now, files, install = approved_plan(monkeypatch)
    plan.update(mutation)
    with pytest.raises(ValueError):
        ci.validate_plan(install(plan), now=now)


@pytest.mark.parametrize("suffix", [".json", ".activation.json", ".recovery.json"])
def test_changed_plan_or_evidence_is_rejected(monkeypatch, suffix):
    plan, now, files, install = approved_plan(monkeypatch)
    plan_id = install(plan)
    files[ci.PLANS / (plan_id + suffix)] += b" "
    with pytest.raises(ValueError, match="digest differs"):
        ci.validate_plan(plan_id, now=now)


def test_recovery_requires_all_evidence_and_checks_each_hash(monkeypatch):
    plan, now, files, install = approved_plan(monkeypatch)
    plan_id = install(plan)
    files[Path("/root/recovery/boot_structure_proof.json")] = b"changed proof"
    with pytest.raises(ValueError, match="digest differs"):
        ci.validate_plan(plan_id, now=now)
    with pytest.raises(ValueError, match="complete offsite"):
        ci.validate_recovery(encoded({"schema_version": 1, "result": "PASS", "evidence": {}}))


def test_no_adapter_means_no_claim_or_worker(monkeypatch):
    monkeypatch.setattr(ci, "load_runtime", lambda: (_ for _ in ()).throw(FileNotFoundError("adapter missing")))
    monkeypatch.setattr(ci.os, "open", lambda *args: pytest.fail("no root write before admission"))
    monkeypatch.setattr(ci, "run", lambda *args, **kwargs: pytest.fail("no worker before admission"))
    with pytest.raises(FileNotFoundError, match="adapter missing"):
        ci.activate("a" * 64)


def test_root_bootstrap_and_retained_queue_have_only_fixed_executable_arguments():
    argv = ci.activation_argv("a" * 64)
    assert argv[-8:] == ['/usr/bin/sudo', '-n', '--', '/usr/bin/python3', '-I', ci.CONTROL, '--worker', 'a' * 64]
    assert '/usr/local/lib/shared-pi-queue/pi_shared_queue.py' in argv
    for property in ("User=pi", "Group=pi", "NoNewPrivileges=no", "ProtectSystem=strict", "ProtectHome=yes",
                     "ProtectControlGroups=yes", "KillMode=control-group", "TimeoutStopSec=900"):
        assert "--property=" + property in argv


def test_login_subprocess_never_uses_a_shell_or_caller_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(ci.subprocess, "run", lambda argv, **kwargs:
                        calls.append((argv, kwargs)) or SimpleNamespace(returncode=0))
    assert ci.login_main(["-c", "status"]) == 0
    argv, options = calls[0]
    assert argv == ["/usr/bin/sudo", "-n", "--", ci.CONTROL]
    assert options["shell"] is False
    assert options["env"] == ci.ENV
    assert json.loads(options["input"]) == {"action": "status"}


@pytest.mark.parametrize("argv", [[], ["-l"], ["-c", "status", "extra"], ["--help"]])
def test_interactive_login_is_denied(argv):
    with pytest.raises(ValueError):
        ci.login_main(argv)


def test_replayed_plan_does_not_launch_worker(monkeypatch, tmp_path):
    # Exercise POSIX exclusive-creation semantics on Windows without claiming
    # to test its unavailable O_NOFOLLOW support. Linux ownership tests differ.
    if not hasattr(ci.os, "O_NOFOLLOW"):
        monkeypatch.setattr(ci.os, "O_NOFOLLOW", 0, raising=False)
    plan_id = "a" * 64
    monkeypatch.setattr(ci, 'load_runtime', lambda: {'pi_ci_activate': SimpleNamespace(
        plan_context=lambda value: {'plan': {'target_commit': 'b' * 40}})})
    monkeypatch.setattr(ci, "require_root_path", lambda *args, **kwargs: None)
    monkeypatch.setattr(ci, "STATE", tmp_path)
    (tmp_path / (plan_id + ".claimed.json")).write_text("retained ambiguous transaction")
    monkeypatch.setattr(ci, "run", lambda *args, **kwargs: pytest.fail("no replay"))
    with pytest.raises(FileExistsError):
        ci.activate(plan_id)


@pytest.mark.parametrize("uid,mode,links", [(1000, stat.S_IFREG | 0o444, 1),
    (0, stat.S_IFREG | 0o664, 1), (0, stat.S_IFREG | 0o446, 1),
    (0, stat.S_IFLNK | 0o777, 1), (0, stat.S_IFREG | 0o444, 2)])
def test_trusted_file_rejects_nonroot_writable_symlink_and_hardlink(monkeypatch, tmp_path, uid, mode, links):
    path = tmp_path / "plan.json"
    def info(entry):
        if entry == path:
            return SimpleNamespace(st_uid=uid, st_mode=mode, st_nlink=links)
        return SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | 0o755, st_nlink=1)
    monkeypatch.setattr(Path, "lstat", info)
    with pytest.raises(ValueError):
        ci.require_root_path(path)


def test_writable_ancestor_is_rejected_even_if_leaf_is_root_owned(monkeypatch, tmp_path):
    path = tmp_path / "plan.json"
    def info(entry):
        if entry == path:
            return SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o444, st_nlink=1)
        return SimpleNamespace(st_uid=0, st_mode=stat.S_IFDIR | (0o775 if entry == tmp_path else 0o755), st_nlink=1)
    monkeypatch.setattr(Path, "lstat", info)
    with pytest.raises(ValueError, match="exclusively root"):
        ci.require_root_path(path)


def test_status_does_not_claim_verified_deployment_or_expose_environment(monkeypatch):
    calls = []
    monkeypatch.setattr(ci, "run", lambda argv, **kwargs:
                        calls.append(argv) or SimpleNamespace(returncode=0, stdout="LoadState=loaded\nActiveState=active\n"))
    result = ci.status()
    assert result["deployment_acceptance"] == "NOT_ASSESSED"
    assert set(result["units"]) == set(ci.UNITS)
    assert len(calls) == len(ci.UNITS)
    assert all("Environment" not in " ".join(argv) for argv in calls)


def test_uncommissioned_installation_cannot_admit_worker_or_write(monkeypatch):
    monkeypatch.setattr(ci, 'trusted_bytes', lambda *args: b'{"schema":"ar-local-ci-runtime-v1"}')
    monkeypatch.setattr(ci, "run", lambda *args, **kwargs: pytest.fail("foundation cannot launch worker"))
    with pytest.raises(ValueError, match="complete commissioned"):
        ci.activate("a" * 64)


@pytest.mark.parametrize('version', [True, False, 1.0, '1', None])
def test_root_approvals_require_exact_integer_schema_version(monkeypatch, version):
    plan, now, files, install = approved_plan(monkeypatch)
    plan['schema_version'] = version
    with pytest.raises(ValueError, match='deployment plan'):
        ci.validate_plan(install(plan), now=now)
    recovery = {'schema_version': version, 'result': 'PASS', 'evidence': {}}
    with pytest.raises(ValueError, match='recovery approval'):
        ci.validate_recovery(encoded(recovery))


def test_installer_entrypoint_rejects_before_payload_import_or_install(tmp_path):
    import os
    import shutil
    import subprocess
    if os.name != 'posix' or not Path('/usr/bin/python3').exists() or not shutil.which('bash'):
        pytest.skip('actual POSIX bash installer entrypoint is qualified on Linux')
    source = Path(__file__).resolve().parents[1] / 'deploy/pi/install-ci-access.sh'
    fixture = tmp_path / 'install-ci-access.sh'
    fixture.write_bytes(source.read_bytes())
    (tmp_path / 'pi_ci_access.py').write_text("raise RuntimeError('PAYLOAD_IMPORTED_UNSAFELY')\n")
    # Missing/unprotected staging approval guarantees the pure trust validator
    # rejects. Even a regression skipping it encounters the sentinel exception
    # before any installation command; no real destination can be modified.
    response = subprocess.run(['bash', str(fixture), '--install', str(tmp_path / 'recovery.json'),
        'a' * 64, str(tmp_path / 'staging.json'), 'b' * 64], capture_output=True, text=True, timeout=15)
    assert response.returncode != 0
    assert 'staged files must be read-only and exclusively root controlled' in response.stderr
    assert 'PAYLOAD_IMPORTED_UNSAFELY' not in response.stdout + response.stderr
    assert 'Explicit installation requires root' not in response.stderr


@pytest.fixture
def staging_validator(monkeypatch, tmp_path):
    """Exercise the actual inline validator with simulated POSIX ownership.

    No untrusted payload is imported. File bytes are real; metadata is injected
    so the root-only ownership contract is testable in unprivileged Linux CI and
    Windows, without claiming native installation or filesystem acceptance.
    """
    script = (Path(__file__).resolve().parents[1] / "deploy/pi/install-ci-access.sh").read_text()
    code = script.split("<<'TRUST_PY'\n", 1)[1].split("\nTRUST_PY", 1)[0]
    namespace = {"__name__": "ci_staging_validator_test"}
    exec(compile(code, "installer-inline-trust-validator", "exec"), namespace)
    installer = tmp_path / "install-ci-access.sh"
    payload = tmp_path / "pi_ci_access.py"
    installer.write_bytes(b"# reviewed installer bytes\n")
    payload.write_bytes(b"raise RuntimeError('payload must never execute during trust validation')\n")
    approval = tmp_path / "staging-approval.json"
    approval.write_bytes(encoded({"schema_version": 1, "source_commit": "a" * 40, "files": {
        installer.name: digest(installer.read_bytes()), payload.name: digest(payload.read_bytes())}}))
    files = {installer, payload, approval}
    overrides = {}

    def metadata(entry):
        default = {"st_uid": 0, "st_mode": stat.S_IFREG | 0o444 if entry in files else stat.S_IFDIR | 0o755,
                   "st_nlink": 1, "st_size": len(entry.read_bytes()) if entry in files else 0}
        return SimpleNamespace(**(default | overrides.get(entry, {})))

    monkeypatch.setattr(Path, "lstat", metadata)
    real_os = namespace["os"]
    namespace["os"] = SimpleNamespace(path=real_os.path, open=real_os.open, fdopen=real_os.fdopen,
        O_RDONLY=real_os.O_RDONLY, O_NOFOLLOW=getattr(real_os, "O_NOFOLLOW", 0),
        fstat=lambda fd: SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o444,
                                        st_nlink=1, st_size=real_os.fstat(fd).st_size))
    return namespace["validate_staging"], installer, payload, approval, overrides


def test_protected_staging_validates_bytes_without_importing_payload(staging_validator):
    validate, installer, payload, approval, overrides = staging_validator
    validate(str(installer), str(approval), digest(approval.read_bytes()))


@pytest.mark.parametrize("which,changes", [
    ("installer", {"st_uid": 1000}), ("payload", {"st_uid": 1000}),
    ("installer", {"st_mode": stat.S_IFREG | 0o644}),
    ("payload", {"st_mode": stat.S_IFREG | 0o444 | 0o020}),
    ("payload", {"st_mode": stat.S_IFLNK | 0o777}), ("payload", {"st_nlink": 2}),
    ("ancestor", {"st_uid": 1000}), ("ancestor", {"st_mode": stat.S_IFDIR | 0o775}),
    ("approval", {"st_mode": stat.S_IFREG | 0o644}),
])
def test_untrusted_staging_cannot_be_imported_or_installed(staging_validator, which, changes):
    validate, installer, payload, approval, overrides = staging_validator
    target = {"installer": installer, "payload": payload, "approval": approval, "ancestor": installer.parent}[which]
    overrides[target] = changes
    with pytest.raises(ValueError):
        validate(str(installer), str(approval), digest(approval.read_bytes()))


@pytest.mark.parametrize("which", ["installer", "payload"])
def test_staged_bytes_must_match_independent_review(staging_validator, which):
    validate, installer, payload, approval, overrides = staging_validator
    (installer if which == "installer" else payload).write_bytes(b"unreviewed replacement\n")
    with pytest.raises(ValueError, match="differ from independent review"):
        validate(str(installer), str(approval), digest(approval.read_bytes()))


def test_approval_itself_is_bound_to_external_operator_hash(staging_validator):
    validate, installer, payload, approval, overrides = staging_validator
    with pytest.raises(ValueError, match="approval hash differs"):
        validate(str(installer), str(approval), "0" * 64)
