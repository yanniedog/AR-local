"""A selected LAN route must have a correlated terminal result on caught errors."""
import json
from types import SimpleNamespace

import pytest

import laptop_backup_atomic as atomic
import laptop_backup_scheduled as scheduled
import laptop_backup_user_session as user


@pytest.mark.parametrize("fault", [None, "arguments", "lock", "catalog", "receiver", "parser", "nonzero"])
def test_downstream_failures_terminalize_the_original_route(tmp_path, monkeypatch, fault):
    config = {"target": str(tmp_path), "receiver": str(tmp_path / "source"),
              "candidate_sha": "a" * 40, "protected_sha": "b" * 40,
              "operator_sid": "test-user", "authority": "D-015-USER-SESSION-NO-UAC",
              "legacy_task": "untouched", "recovery_image": str(tmp_path / "image")}
    transport = dict(ssh_user="pi", ssh_port=22, ssh_path="ssh", ssh_sha256="c" * 64,
                     scp_path="scp", scp_sha256="d" * 64, ssh_identity_path="key",
                     ssh_known_hosts_path="known-hosts")
    if fault == "arguments":
        del transport["ssh_port"]
    monkeypatch.setattr(user, "verify_release", lambda config: None)
    monkeypatch.setattr(user, "allowed_start", lambda now: True)
    monkeypatch.setattr(user, "legacy_idle", lambda name: None)
    monkeypatch.setattr(user, "transport_contract", lambda: transport)
    monkeypatch.setattr(user.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        stdout=json.dumps({"endpoint": "192.168.1.2", "source": "name_lookup"})))

    class Lock:
        def __init__(self, path):
            pass
        def __enter__(self):
            if fault == "lock":
                raise RuntimeError("injected lock collision")
        def __exit__(self, *args):
            return False

    monkeypatch.setattr(atomic, "ReceiverLock", Lock)

    def catalog(target):
        if fault == "catalog":
            raise OSError("injected catalog failure")

    def run(args):
        if fault == "parser":
            raise SystemExit(2)
        if fault == "receiver":
            raise ValueError("injected receiver failure")
        return 7 if fault == "nonzero" else 0

    monkeypatch.setattr(user, "initialize_catalog", catalog)
    monkeypatch.setattr(scheduled, "main", run)
    if fault in {"arguments", "lock", "catalog", "receiver", "parser"}:
        with pytest.raises((KeyError, RuntimeError, OSError, ValueError, SystemExit)) as caught:
            user.execute(config, "run", "e" * 64)
        if fault == "parser":
            assert caught.value.code == 2
    else:
        assert user.execute(config, "run", "e" * 64) == (7 if fault == "nonzero" else 0)
    paths = list((tmp_path / "user-session-executions").glob("*.json"))
    assert len(paths) == 2
    records = [(path, json.loads(path.read_bytes())) for path in paths]
    route_path, route = next(item for item in records if item[1]["result"] == "RUNNING")
    terminal = next(value for _, value in records if value["result"] != "RUNNING")
    assert terminal["result"] == ("FAIL" if fault else "PASS")
    assert terminal["execution_id"] == route["execution_id"]
    assert terminal["route_record_path"] == str(route_path)
    assert route["endpoint"] == "192.168.1.2"
    assert route["elevated"] is False and terminal["elevated"] is False
    if fault in {"arguments", "lock", "catalog", "receiver", "parser"}:
        assert terminal["error_type"]
