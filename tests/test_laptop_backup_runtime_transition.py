import json
from types import SimpleNamespace

import pytest

import laptop_backup_runtime_transition as transition
import laptop_backup_scheduled as scheduled
import laptop_backup_user_session as user
from tests.test_laptop_backup_scheduled_lineage import _args, _baseline


def test_unverified_cli_transition_is_rejected(monkeypatch):
    monkeypatch.delenv("AR_USER_BACKUP_CONFIG_SHA256", raising=False)
    with pytest.raises(ValueError, match="verified user-session"):
        transition.authority(SimpleNamespace(user_runtime_transition=True))


def test_pinned_configuration_must_match_the_actual_invocation(monkeypatch):
    previous = {"production_sha": "9"*40, "receiver_sha": "c"*40, "record_sha256": "a"*64}
    config = {"target": "target", "candidate_sha": "d"*40, "protected_sha": "8"*40,
              "operator_sid": "operator", "previous_runtime": previous}
    monkeypatch.setenv("AR_USER_BACKUP_CONFIG_SHA256", "f"*64)
    monkeypatch.setattr(user, "load_config", lambda *args: config)
    monkeypatch.setattr(user, "verify_release", lambda value: None)
    args = SimpleNamespace(user_runtime_transition=True, target="target", candidate_code_sha="d"*40,
                           protected_code_sha="8"*40, operator="operator")
    assert transition.authority(args) == previous
    args.protected_code_sha = "7"*40
    with pytest.raises(ValueError, match="pinned configuration"):
        transition.authority(args)


@pytest.mark.parametrize("wrong_digest", [False, True])
def test_runtime_transition_preserves_and_binds_exact_prior_receipt(tmp_path, monkeypatch, wrong_digest):
    target = tmp_path / "backup"
    baseline = _baseline(target)
    path = target / baseline["record_path"]
    before = path.read_bytes()
    previous = {"production_sha": "9"*40, "receiver_sha": "c"*40,
                "record_sha256": "f"*64 if wrong_digest else baseline["record_sha256"]}
    monkeypatch.setattr(transition, "authority", lambda args: previous)
    args = _args()
    args.protected_code_sha = "8"*40
    args.candidate_code_sha = "d"*40
    if wrong_digest:
        with pytest.raises(ValueError, match="pinned receipt"):
            scheduled.record_execution(target, args, "BLOCKED", "BACKUP_REQUIRED", {})
    else:
        new = scheduled.record_execution(target, args, "BLOCKED", "BACKUP_REQUIRED", {})
        record = json.loads(new.read_bytes())
        assert record["protected_code_sha"] == "8"*40
        assert record["previous_execution"]["record_sha256"] == baseline["record_sha256"]
        # Subsequent records follow the new identity, rather than reusing the old pin.
        following = scheduled.record_execution(target, args, "BLOCKED", "BACKUP_REQUIRED", {})
        assert json.loads(following.read_bytes())["previous_execution"]["record_path"] == new.relative_to(target).as_posix()
    assert path.read_bytes() == before


def test_unapproved_old_production_identity_is_rejected(tmp_path):
    target = tmp_path / "backup"
    _baseline(target)
    args = _args()
    args.protected_code_sha = "8"*40
    with pytest.raises(ValueError, match="production identity"):
        scheduled.prepare_execution_lineage(target, args)
