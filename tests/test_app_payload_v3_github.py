from __future__ import annotations

import inspect
import json
import subprocess
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app_payload_v3_github
import app_payload_v3_state
from app_payload_v3_github import (
    CANONICAL_CANDIDATE_WORKFLOW,
    LOCK_LEASE_SECONDS,
    MAX_PUBLIC_BYTES,
    GitHubPromotionBackend,
    public_fetch,
    validate_candidate_run_metadata,
)
from app_payload_v3_state import (
    CANDIDATE_ARTIFACT_BINDING_CONTRACT,
    CandidateArtifactBindingContract,
)
from app_payload_v3_promotion import (
    ConcurrencyError,
    PromotionError,
    _verified_execution_backend,
)
from app_payload_v3_state import LOCK_FILENAME
from cdr_domain.serialize import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[1]
PRODUCER_COMMIT = "6f696ecc3a61198b90ad58f8b90b086e866a26e4"


def _json(payload: bytes | None) -> dict[str, object]:
    assert payload is not None
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


class _Response:
    def __init__(self, payload: bytes, declared: int) -> None:
        self.payload = payload
        self.headers = {"Content-Length": str(declared)}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int) -> bytes:
        return self.payload


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response

    def open(self, *_args, **_kwargs):
        return self.response


def test_public_fetch_accepts_exact_largest_declared_cap_and_rejects_larger(
    monkeypatch,
):
    assert MAX_PUBLIC_BYTES == 33_554_432
    monkeypatch.setattr(
        app_payload_v3_github.urllib.request,
        "build_opener",
        lambda *_args: _Opener(_Response(b"verified", MAX_PUBLIC_BYTES)),
    )
    assert public_fetch(
        "https://github.com/yanniedog/AR-local/releases/download/tag/asset",
        MAX_PUBLIC_BYTES,
    ) == b"verified"
    monkeypatch.setattr(
        app_payload_v3_github.urllib.request,
        "build_opener",
        lambda *_args: _Opener(_Response(b"", MAX_PUBLIC_BYTES + 1)),
    )
    with pytest.raises(PromotionError, match="exceeds"):
        public_fetch(
            "https://github.com/yanniedog/AR-local/releases/download/tag/asset",
            MAX_PUBLIC_BYTES,
        )
    with pytest.raises(PromotionError, match="byte limit"):
        public_fetch(
            "https://github.com/yanniedog/AR-local/releases/download/tag/asset",
            MAX_PUBLIC_BYTES + 1,
        )


def test_backend_and_workflow_have_only_append_only_safe_write_surfaces():
    backend_source = inspect.getsource(GitHubPromotionBackend)
    assert "--clobber" not in backend_source
    assert '"force": True' not in backend_source
    assert '"force": False' in backend_source
    assert "release delete" not in backend_source
    assert "git/refs" in backend_source

    workflow = (
        ROOT / ".github" / "workflows" / "app-payload-v3-promote.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "push:" not in workflow
    assert "default: false" in workflow
    assert "group: app-payload-v3-promotion" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "environment: app-payload-v3-promotion" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "inputs.execute == true" in workflow
    assert "contents: write" in workflow
    assert workflow.count("contents: write") == 1
    assert workflow.count("GH_TOKEN: ${{ github.token }}") == 3
    assert workflow.count("persist-credentials: false") == 2
    assert workflow.count("ref: ${{ github.sha }}") == 2
    assert "ref: main" not in workflow
    assert "timeout-minutes: 60" in workflow
    assert "AR_V3_PROMOTION_APPROVED" in workflow
    assert workflow.count("--verify-candidate-run") == 2
    assert workflow.count("--expected-producer-commit") == 2
    assert workflow.count("--candidate-run-id") == 1
    assert 'test "$CANDIDATE_ARTIFACT_NAME" = "payload-v3-candidate"' in workflow
    assert workflow.find("Verify canonical producer-run provenance") < workflow.find(
        "Download exact canonical candidate artifact"
    )
    assert workflow.rfind("Re-verify canonical producer-run provenance") < workflow.rfind(
        "Download exact canonical candidate artifact"
    )
    assert "--execute" in workflow
    assert "force" not in workflow.lower()
    assert "delete" not in workflow.lower()


def test_direct_execute_stays_blocked_without_archive_to_tree_binding(monkeypatch):
    calls: list[str] = []

    class ProvenanceBackend:
        def __init__(self, repo: str) -> None:
            assert repo == "yanniedog/AR-local"

        def verify_candidate_run(self, run_id: str) -> str:
            calls.append(run_id)
            return PRODUCER_COMMIT

    monkeypatch.setattr(
        app_payload_v3_github, "GitHubPromotionBackend", ProvenanceBackend
    )

    assert CANDIDATE_ARTIFACT_BINDING_CONTRACT is None
    with pytest.raises(PromotionError, match="artifact-byte provenance"):
        _verified_execution_backend(
            "yanniedog/AR-local", "12345", PRODUCER_COMMIT
        )
    assert calls == []
    monkeypatch.setattr(
        app_payload_v3_state,
        "CANDIDATE_ARTIFACT_BINDING_CONTRACT",
        CandidateArtifactBindingContract(
            workflow_path=CANONICAL_CANDIDATE_WORKFLOW,
            artifact_name="payload-v3-candidate",
            archive_digest_algorithm="sha256",
            inventory_contract_sha256="f" * 64,
        ),
    )
    with pytest.raises(PromotionError, match="archive-to-tree verification"):
        _verified_execution_backend(
            "yanniedog/AR-local", "12345", PRODUCER_COMMIT
        )
    assert calls == []
    with pytest.raises(PromotionError, match="requires a candidate run ID"):
        _verified_execution_backend(
            "yanniedog/AR-local", None, PRODUCER_COMMIT
        )


def test_batched_candidate_census_stays_below_api_budget_over_1000_releases(
    monkeypatch,
):
    releases = []
    refs = []
    for revision in range(1, 1002):
        tag = (
            "app-payload-v3-candidate-gen-2026-08-14-"
            f"r{revision:04d}-aaaaaaaaaaaa"
        )
        releases.append(
            {
                "tag_name": tag,
                "name": f"candidate {revision}",
                "body": "notes",
                "draft": False,
                "prerelease": False,
                "assets": [{"name": f"{revision:064x}.json"}],
            }
        )
        refs.append(
            {
                "ref": f"refs/tags/{tag}",
                "object": {"type": "commit", "sha": PRODUCER_COMMIT},
            }
        )
    calls: list[list[str]] = []
    backend = GitHubPromotionBackend()

    def run(args, **_kwargs):
        calls.append(list(args))
        payload = refs if "matching-refs" in args[-1] else releases
        return subprocess.CompletedProcess(args, 0, json.dumps([payload]), "")

    monkeypatch.setattr(backend, "_run", run)

    records = backend.list_candidate_releases()

    assert len(records) == 1001
    assert len(calls) == 2
    assert all("--paginate" in call and "--slurp" in call for call in calls)
    assert calls[1][-1].endswith("?per_page=100")
    conservative_paginated_requests = sum(
        (len(items) + 99) // 100 for items in (releases, refs)
    )
    assert conservative_paginated_requests == 22
    assert conservative_paginated_requests < 100
    assert records[-1].target_commit == PRODUCER_COMMIT


def test_batched_candidate_census_rejects_moved_or_missing_tag_provenance(
    monkeypatch,
):
    tag = "app-payload-v3-candidate-gen-2026-08-14-r0001-aaaaaaaaaaaa"
    release = {
        "tag_name": tag,
        "name": "candidate",
        "body": "notes",
        "draft": False,
        "prerelease": False,
        "assets": [{"name": f"{'a' * 64}.json"}],
    }
    backend = GitHubPromotionBackend()
    outputs = iter((json.dumps([[release]]), json.dumps([[]])))
    monkeypatch.setattr(
        backend,
        "_run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args, 0, next(outputs), ""
        ),
    )

    with pytest.raises(PromotionError, match="metadata is malformed"):
        backend.list_candidate_releases()


def test_github_control_install_is_non_force_and_expected_head_bound(monkeypatch):
    backend = GitHubPromotionBackend()
    expected = "a" * 40
    prepared = "b" * 40
    observed = iter((expected, prepared))
    calls: list[tuple[str, str, Mapping[str, object] | None]] = []
    monkeypatch.setattr(backend, "_ref_head", lambda _branch: next(observed))

    def api(method, endpoint, body=None, **_kwargs):
        calls.append((method, endpoint, body))
        return {}

    monkeypatch.setattr(backend, "_api", api)

    backend.install_control_head(expected, prepared)

    assert calls == [
        (
            "PATCH",
            "repos/yanniedog/AR-local/git/refs/heads/app-payload-v3-control",
            {"sha": prepared, "force": False},
        )
    ]


def test_github_control_install_reconciles_accepted_write_after_api_error(
    monkeypatch,
):
    backend = GitHubPromotionBackend()
    expected = "a" * 40
    prepared = "b" * 40
    observed = iter((expected, prepared))
    monkeypatch.setattr(backend, "_ref_head", lambda _branch: next(observed))

    def fail_after_acceptance(*_args, **_kwargs):
        raise PromotionError("injected lost response")

    monkeypatch.setattr(backend, "_api", fail_after_acceptance)

    backend.install_control_head(expected, prepared)


def test_github_owner_lock_rejects_malformed_prior_document(monkeypatch):
    backend = GitHubPromotionBackend()
    monkeypatch.setattr(backend, "_ref_head", lambda _branch: "a" * 40)
    monkeypatch.setattr(
        backend,
        "_fetch_raw",
        lambda _commit, _path: b'{"state":"released"}',
    )

    with pytest.raises(ConcurrencyError, match="lock document is malformed"):
        backend.acquire_lock("b" * 32, PRODUCER_COMMIT)


def _lock_bytes(
    *,
    owner: str,
    recorded_at: str,
    lease_expires_at: str,
    state: str = "acquired",
    recovered_from: str | None = None,
) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": 1,
            "state": state,
            "owner_token": owner,
            "target_commit": PRODUCER_COMMIT,
            "recorded_at": recorded_at,
            "lease_expires_at": lease_expires_at,
            "recovered_from_owner_token": recovered_from,
        }
    )


def test_github_owner_lock_rejects_active_unexpired_lease(monkeypatch):
    old_owner = "a" * 32
    backend = GitHubPromotionBackend(
        clock=lambda: datetime(2026, 8, 15, 1, tzinfo=timezone.utc)
    )
    monkeypatch.setattr(backend, "_ref_head", lambda _branch: "1" * 40)
    monkeypatch.setattr(
        backend,
        "_fetch_raw",
        lambda _commit, _path: _lock_bytes(
            owner=old_owner,
            recorded_at="2026-08-15T00:00:00Z",
            lease_expires_at="2026-08-15T02:00:00Z",
        ),
    )
    monkeypatch.setattr(
        backend,
        "_append_commit",
        lambda *_args, **_kwargs: pytest.fail("active lease must not be replaced"),
    )

    with pytest.raises(ConcurrencyError, match="lock is active"):
        backend.acquire_lock("b" * 32, PRODUCER_COMMIT)


def test_github_owner_lock_recovers_expired_lease_by_head_cas(monkeypatch):
    old_owner = "a" * 32
    new_owner = "b" * 32
    old_head = "1" * 40
    new_head = "2" * 40
    old_payload = _lock_bytes(
        owner=old_owner,
        recorded_at="2026-08-15T00:00:00Z",
        lease_expires_at="2026-08-15T02:00:00Z",
    )
    backend = GitHubPromotionBackend(
        clock=lambda: datetime(2026, 8, 15, 3, tzinfo=timezone.utc)
    )
    observed_head = old_head
    observed_payload = old_payload

    def ref_head(_branch: str) -> str:
        return observed_head

    def fetch_raw(_commit: str, _path: str) -> bytes:
        return observed_payload

    def append_commit(
        branch: str,
        expected_head: str,
        files: Mapping[str, bytes],
        message: str,
    ) -> str:
        nonlocal observed_head, observed_payload
        assert branch == "app-payload-v3-promotion-lock"
        assert expected_head == old_head
        assert message == f"acquire v3 promotion {new_owner}"
        observed_payload = files[LOCK_FILENAME]
        observed_head = new_head
        return new_head

    monkeypatch.setattr(backend, "_ref_head", ref_head)
    monkeypatch.setattr(backend, "_fetch_raw", fetch_raw)
    monkeypatch.setattr(backend, "_append_commit", append_commit)

    assert backend.acquire_lock(new_owner, PRODUCER_COMMIT) == new_head
    recovered = _json(observed_payload)
    assert recovered == {
        "schema_version": 1,
        "state": "acquired",
        "owner_token": new_owner,
        "target_commit": PRODUCER_COMMIT,
        "recorded_at": "2026-08-15T03:00:00Z",
        "lease_expires_at": "2026-08-15T05:00:00Z",
        "recovered_from_owner_token": old_owner,
    }
    assert LOCK_LEASE_SECONDS == 7_200
    with pytest.raises(ConcurrencyError, match="owner token changed"):
        backend.release_lock(old_owner)


def _trusted_run_metadata() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    run = {
        "status": "completed",
        "conclusion": "success",
        "path": CANONICAL_CANDIDATE_WORKFLOW,
        "event": "workflow_dispatch",
        "head_branch": "main",
        "head_sha": PRODUCER_COMMIT,
        "repository": {"full_name": "yanniedog/AR-local"},
        "head_repository": {"full_name": "yanniedog/AR-local"},
    }
    branch = {"name": "main", "protected": True}
    comparison = {
        "status": "ahead",
        "merge_base_commit": {"sha": PRODUCER_COMMIT},
    }
    return run, branch, comparison


def test_candidate_run_provenance_accepts_only_allowlisted_protected_main():
    run, branch, comparison = _trusted_run_metadata()

    assert validate_candidate_run_metadata(run, branch, comparison) == PRODUCER_COMMIT
    assert not (ROOT / CANONICAL_CANDIDATE_WORKFLOW).exists()


@pytest.mark.parametrize(
    "run_change,branch_change,comparison_change,message",
    [
        ({"conclusion": "failure"}, {}, {}, "completed successfully"),
        (
            {"repository": {"full_name": "attacker/example"}},
            {},
            {},
            "canonical repository",
        ),
        ({"path": ".github/workflows/app-ci.yml"}, {}, {}, "not allowlisted"),
        ({"head_sha": "7" * 40}, {}, {}, "not retained"),
        ({}, {"protected": False}, {}, "not reported as protected"),
    ],
)
def test_candidate_run_provenance_rejects_forged_run_workflow_and_head(
    run_change, branch_change, comparison_change, message
):
    run, branch, comparison = _trusted_run_metadata()
    run.update(run_change)
    branch.update(branch_change)
    comparison.update(comparison_change)

    with pytest.raises(PromotionError, match=message):
        validate_candidate_run_metadata(run, branch, comparison)
