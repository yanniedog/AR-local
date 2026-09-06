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


@pytest.mark.parametrize("matches", [False, True])
def test_historical_coverage_requires_both_previous_runtime_identities(tmp_path, matches):
    import laptop_pull_backup as receiver
    from tests.test_laptop_pull_backup import LEGACY_PLAN_VERSION, LEGACY_PLAN_COMMIT, LEGACY_PLAN_SHA256, LEGACY_PLAN_RAW_SHA256
    path = tmp_path / "observations/2026-05-22/old/receipt.json"
    path.parent.mkdir(parents=True)
    receipt = {"result": "PASS", "kind": "observation", "observation_date": "2026-05-22",
               "plan_document_id": receiver.PLAN_DOCUMENT_ID, "plan_version": LEGACY_PLAN_VERSION,
               "plan_git_commit": LEGACY_PLAN_COMMIT, "plan_sha256": LEGACY_PLAN_SHA256,
               "plan_raw_sha256": LEGACY_PLAN_RAW_SHA256, "protected_code_sha": "9"*40,
               "candidate_code_sha": ("c" if matches else "e")*40,
               "source_manifest_sha256": "d"*64, "archive_sha256": "e"*64,
               "checks": {"observation": {"quick_check": "ok"}}, "deviations": []}
    path.write_bytes(receiver.canonical_json_bytes(receipt))
    before = path.read_bytes()
    receiver.append_catalog(tmp_path, receipt, path)
    result = scheduled.inventory_status(tmp_path, [{"date": "2026-05-22", "status": "completed"}],
        {"diagnostics": {}}, protected_sha="8"*40, plan_commit=receiver.PLAN_GIT_COMMIT,
        previous_runtime={"production_sha": "9"*40, "receiver_sha": "c"*40})
    assert (result["status"] == "UP_TO_DATE") is matches
    assert path.read_bytes() == before


@pytest.mark.parametrize("matches", [False, True])
def test_diagnostic_coverage_uses_the_complete_previous_identity(tmp_path, monkeypatch, matches):
    import laptop_pull_backup as receiver
    path = tmp_path / "diagnostic/receipt.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"protected_code_sha": "9"*40,
                                "candidate_code_sha": ("c" if matches else "e")*40}))
    monkeypatch.setattr(receiver, "catalog_entries", lambda _: [{
        "kind": "diagnostic", "run_date": "2026-05-22", "receipt_path": "diagnostic/receipt.json"}])
    def verified(*args, **kwargs):
        actual = json.loads(path.read_text())
        if (kwargs["protected_sha"] != actual["protected_code_sha"]
                or kwargs["candidate_sha"] != actual["candidate_code_sha"]):
            raise ValueError("receipt identity mismatch")
        return actual, {}, path
    monkeypatch.setattr(scheduled, "verified_receipt", verified)
    monkeypatch.setattr(scheduled, "content_revision", lambda _: "a"*64)
    report = scheduled.inventory_status(tmp_path, [],
        {"diagnostics": {"2026-05-22": {"content_revision": "a"*64}}},
        protected_sha="8"*40, plan_commit=receiver.PLAN_GIT_COMMIT,
        previous_runtime={"production_sha": "9"*40, "receiver_sha": "c"*40})
    assert (report["status"] == "UP_TO_DATE") is matches
