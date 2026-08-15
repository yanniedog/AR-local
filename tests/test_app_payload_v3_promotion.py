from __future__ import annotations

import hashlib
import inspect
import json
import urllib.parse
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

import app_payload_v3_github
from app_payload_v3_github import (
    CANONICAL_CANDIDATE_WORKFLOW,
    MAX_PUBLIC_BYTES,
    GitHubPromotionBackend,
    public_fetch,
    validate_candidate_run_metadata,
)
from app_payload_v3_promotion import (
    CANDIDATE_TAG_PREFIX,
    DATES_INDEX_FILENAME,
    POINTER_FILENAME,
    V3_MANIFEST_LIMIT_BYTES,
    V3_POINTER_LIMIT_BYTES,
    ConcurrencyError,
    PromotionError,
    _remote_bundle,
    load_candidate,
    promote_candidate,
)
from cdr_domain.contract_validation import validate_generation_pointer
from cdr_domain.generation import (
    GenerationInputs,
    build_generation_candidate,
    write_generation_candidate,
)
from cdr_domain.normalize import normalize_product


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "canonical_domain_real_observations.json"
PRODUCER_COMMIT = "6f696ecc3a61198b90ad58f8b90b086e866a26e4"


def _observation(name: str):
    item = json.loads(FIXTURE.read_text(encoding="utf-8"))["observations"][name]
    return normalize_product(
        item["record"],
        dataset=item["dataset"],
        provider_display_name=item["provider"],
        register_holder_id=None,
        authority=f"preserved-fixture:{name}",
        observed_at="2026-08-14T10:00:00+10:00",
        source_path=item["source_path"],
        source_locator=item["source_locator"],
        source_sha256=item["source_sha256"],
        source_kind="preserved_cdr_fixture_projection",
    )


def _candidate_directory(
    tmp_path: Path,
    *,
    observation_date: str = "2026-08-14",
    revision: int = 1,
    state: str = "complete",
    producer_commit: str = PRODUCER_COMMIT,
) -> Path:
    product = _observation("bank_of_melbourne_before_rename")
    provider_states = {product.identity.provider_uid: "complete"}
    discovered = {product.identity.provider_uid: 1}
    failures: dict[str, int] = {}
    if state == "partial":
        failed = _observation("bank_of_china_td_without_structured_term")
        provider_states[failed.identity.provider_uid] = "failed"
        discovered[failed.identity.provider_uid] = 0
        failures[failed.identity.provider_uid] = 1
    ledger_digest = hashlib.sha256(
        f"{observation_date}:{revision}:{state}:{producer_commit}".encode()
    ).hexdigest()
    inputs = GenerationInputs.from_mapping(
        {
            "observation_date": observation_date,
            "observed_at": f"{observation_date}T10:00:00+10:00",
            "observation_state": state,
            "generation_revision": revision,
            "normalization_version": product.normalization_version,
            "producer_commit": producer_commit,
            "prior_ledger_digest": None,
            "ledger_event_digest": ledger_digest,
            "provider_states": provider_states,
            "products_discovered_by_provider": discovered,
            "register_source_states": {"preserved-register": "complete"},
            "failure_records_by_provider": failures,
            "corrupt_failure_records": 0,
        }
    )
    candidate = build_generation_candidate((product,), inputs)
    return write_generation_candidate(candidate, tmp_path / "candidates")


class FakeBackend:
    def __init__(self) -> None:
        self.releases: dict[str, dict[str, object]] = {}
        self.commits: dict[str, dict[str, bytes]] = {}
        self._control_head: str | None = None
        self.lock_owner: str | None = None
        self.events: list[tuple[str, object]] = []
        self.fail_list = False
        self.fail_put_tag: str | None = None
        self.fail_prepare_path: str | None = None
        self.fail_install = False
        self.corrupt_urls: set[str] = set()
        self.omitted_tags: set[str] = set()

    def acquire_lock(self, owner_token: str, target_commit: str) -> str:
        if self.lock_owner is not None:
            raise ConcurrencyError("lock active")
        self.lock_owner = owner_token
        self.events.append(("lock", target_commit))
        return "lock-acquired"

    def release_lock(self, owner_token: str) -> str:
        if self.lock_owner != owner_token:
            raise ConcurrencyError("lock owner changed")
        self.lock_owner = None
        self.events.append(("unlock", owner_token))
        return "lock-released"

    def ensure_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
        exact_metadata: bool,
    ) -> None:
        existing = self.releases.get(tag)
        metadata = {"title": title, "notes": notes, "target": target_commit}
        if existing is None:
            self.releases[tag] = {"metadata": metadata, "assets": {}}
            self.events.append(("release", tag))
        elif exact_metadata and existing["metadata"] != metadata:
            raise PromotionError("immutable release metadata differs")

    def put_immutable_asset(self, tag: str, name: str, payload: bytes) -> None:
        if self.fail_put_tag == tag:
            raise PromotionError("injected asset backend failure")
        assets = self.releases[tag]["assets"]
        assert isinstance(assets, dict)
        existing = assets.get(name)
        if existing is not None and existing != payload:
            raise PromotionError("immutable asset differs")
        assets[name] = payload
        self.events.append(("asset", (tag, name)))

    def list_candidate_tags(self) -> Sequence[str]:
        if self.fail_list:
            raise PromotionError("injected complete-listing failure")
        return sorted(
            tag
            for tag in self.releases
            if tag.startswith(CANDIDATE_TAG_PREFIX) and tag not in self.omitted_tags
        )

    def list_asset_names(self, tag: str) -> Sequence[str]:
        assets = self.releases[tag]["assets"]
        assert isinstance(assets, dict)
        return sorted(assets)

    def fetch_url(self, url: str, max_bytes: int) -> bytes:
        marker = "/releases/download/"
        if marker not in url:
            raise PromotionError("unexpected fake URL")
        remainder = urllib.parse.urlparse(url).path.split(marker, 1)[1]
        tag, name = remainder.split("/", 1)
        assets = self.releases[urllib.parse.unquote(tag)]["assets"]
        assert isinstance(assets, dict)
        payload = assets[urllib.parse.unquote(name)]
        assert isinstance(payload, bytes)
        if url in self.corrupt_urls:
            payload = payload[:-1] + bytes([payload[-1] ^ 1])
        if len(payload) > max_bytes:
            raise PromotionError("fake public response exceeds cap")
        return payload

    def control_head(self) -> str | None:
        return self._control_head

    def fetch_control_file(self, commit: str, path: str) -> bytes | None:
        return self.commits[commit].get(path)

    def prepare_control_commit(
        self,
        parent: str | None,
        files: Mapping[str, bytes],
        message: str,
    ) -> str:
        if self.fail_prepare_path and self.fail_prepare_path in files:
            raise PromotionError("injected prepare failure")
        snapshot = dict(self.commits[parent]) if parent is not None else {}
        snapshot.update(files)
        commit = f"commit-{len(self.commits) + 1}"
        self.commits[commit] = snapshot
        self.events.append(("prepare", (tuple(files), message, commit)))
        return commit

    def install_control_head(
        self, expected_head: str | None, prepared_head: str
    ) -> None:
        if self._control_head != expected_head:
            raise ConcurrencyError("fake control CAS changed")
        if self.fail_install:
            raise PromotionError("injected control install failure")
        self._control_head = prepared_head
        self.events.append(("install", prepared_head))

    def visible(self, path: str) -> bytes | None:
        if self._control_head is None:
            return None
        return self.commits[self._control_head].get(path)


def _json(payload: bytes | None) -> dict[str, object]:
    assert payload is not None
    value = json.loads(payload)
    assert isinstance(value, dict)
    return value


def test_default_is_local_validation_only_and_rejects_extra_candidate_bytes(tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = FakeBackend()

    result = promote_candidate(directory, backend)

    assert result.dry_run is True
    assert backend.events == []
    (directory / "unexpected.txt").write_text("not part of the candidate")
    with pytest.raises(PromotionError, match="unexpected files"):
        load_candidate(directory)


def test_execute_requires_exact_trusted_producer_commit_before_backend_use(tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = FakeBackend()

    with pytest.raises(PromotionError, match="requires a trusted producer commit"):
        promote_candidate(directory, backend, execute=True)
    with pytest.raises(PromotionError, match="differs from its trusted Actions run"):
        promote_candidate(
            directory,
            backend,
            execute=True,
            expected_producer_commit="7" * 40,
        )

    assert backend.events == []


def test_64k_plus_one_local_manifest_is_rejected_before_any_mutation(tmp_path):
    directory = _candidate_directory(tmp_path)
    manifest_path = next(directory.glob("*.json"))
    manifest_path.unlink()
    oversized = b"{" + (b" " * V3_MANIFEST_LIMIT_BYTES)
    replacement = directory / f"{hashlib.sha256(oversized).hexdigest()}.json"
    replacement.write_bytes(oversized)
    backend = FakeBackend()

    with pytest.raises(PromotionError, match="manifest exceeds"):
        promote_candidate(directory, backend)

    assert len(oversized) == 65_537
    assert backend.events == []


def test_64k_plus_one_remote_manifest_is_rejected_at_the_read_boundary():
    class OversizedRemote(FakeBackend):
        def fetch_url(self, _url: str, max_bytes: int) -> bytes:
            assert max_bytes == V3_MANIFEST_LIMIT_BYTES
            return b"{" + (b" " * V3_MANIFEST_LIMIT_BYTES)

    with pytest.raises(PromotionError, match="remote generation manifest exceeds"):
        _remote_bundle(
            OversizedRemote(),
            "https://github.com/yanniedog/AR-local/releases/download/"
            "app-payload-v3-candidate-gen-2026-08-14-r0001-aaaaaaaaaaaa/"
            f"{'a' * 64}.json",
        )


def test_64k_plus_one_remote_pointer_is_rejected_before_release_mutation(tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = FakeBackend()
    backend.commits["prior"] = {
        POINTER_FILENAME: b"{" + (b" " * V3_POINTER_LIMIT_BYTES)
    }
    backend._control_head = "prior"

    with pytest.raises(PromotionError, match="pointer exceeds"):
        promote_candidate(
            directory,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
        )

    assert backend.control_head() == "prior"
    assert not [event for event in backend.events if event[0] == "release"]


def test_bootstrap_stages_index_then_pointer_and_installs_once(tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = FakeBackend()

    result = promote_candidate(
        directory,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
        generated_at=lambda: "2026-08-15T00:00:00Z",
    )

    prepares = [event for event in backend.events if event[0] == "prepare"]
    installs = [event for event in backend.events if event[0] == "install"]
    assert [tuple(event[1][0]) for event in prepares] == [
        (DATES_INDEX_FILENAME,),
        (POINTER_FILENAME,),
    ]
    assert installs == [("install", result.pointer_commit)]
    assert backend.control_head() == result.pointer_commit
    assert result.index_commit != result.pointer_commit
    assert result.pointer_changed is True
    assert result.dates_index_changed is True
    index = _json(backend.visible(DATES_INDEX_FILENAME))
    pointer = _json(backend.visible(POINTER_FILENAME))
    assert index["count"] == 1
    assert index["dates"][0]["generation_id"] == result.generation_id
    assert pointer["latest_complete"]["generation_id"] == result.generation_id
    assert pointer["latest_observation"] == pointer["latest_complete"]
    assert backend.lock_owner is None


@pytest.mark.parametrize(
    "failure_path,fail_install",
    [
        (DATES_INDEX_FILENAME, False),
        (POINTER_FILENAME, False),
        (None, True),
    ],
)
def test_backend_failure_before_final_cas_cannot_advance_dates_or_pointer(
    tmp_path, failure_path, fail_install
):
    directory = _candidate_directory(tmp_path)
    backend = FakeBackend()
    backend.fail_prepare_path = failure_path
    backend.fail_install = fail_install

    with pytest.raises(PromotionError, match="injected"):
        promote_candidate(
            directory,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
        )

    assert backend.control_head() is None
    assert backend.visible(DATES_INDEX_FILENAME) is None
    assert backend.visible(POINTER_FILENAME) is None
    assert backend.lock_owner is None


def test_listing_uncertainty_retains_the_verified_prior_control_state(tmp_path):
    first = _candidate_directory(tmp_path / "first")
    second = _candidate_directory(
        tmp_path / "second", observation_date="2026-08-15"
    )
    backend = FakeBackend()
    promote_candidate(
        first,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    prior_head = backend.control_head()
    prior_index = backend.visible(DATES_INDEX_FILENAME)
    prior_pointer = backend.visible(POINTER_FILENAME)
    backend.fail_list = True

    with pytest.raises(PromotionError, match="complete-listing"):
        promote_candidate(
            second,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
        )

    assert backend.control_head() == prior_head
    assert backend.visible(DATES_INDEX_FILENAME) == prior_index
    assert backend.visible(POINTER_FILENAME) == prior_pointer


def test_successful_but_incomplete_listing_cannot_drop_a_prior_date(tmp_path):
    first = _candidate_directory(tmp_path / "first")
    second = _candidate_directory(
        tmp_path / "second", observation_date="2026-08-15"
    )
    backend = FakeBackend()
    initial = promote_candidate(
        first,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    prior_head = backend.control_head()
    prior_index = backend.visible(DATES_INDEX_FILENAME)
    prior_pointer = backend.visible(POINTER_FILENAME)
    backend.omitted_tags.add(initial.candidate_tag)

    with pytest.raises(PromotionError, match="cannot drop or regress"):
        promote_candidate(
            second,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
        )

    assert backend.control_head() == prior_head
    assert backend.visible(DATES_INDEX_FILENAME) == prior_index
    assert backend.visible(POINTER_FILENAME) == prior_pointer


def test_partial_advances_observation_but_not_complete_or_dates(tmp_path):
    complete = _candidate_directory(tmp_path / "complete")
    partial = _candidate_directory(
        tmp_path / "partial", observation_date="2026-08-15", state="partial"
    )
    backend = FakeBackend()
    first = promote_candidate(
        complete,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    first_index = backend.visible(DATES_INDEX_FILENAME)

    second = promote_candidate(
        partial,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )

    pointer = _json(backend.visible(POINTER_FILENAME))
    assert pointer["latest_observation"]["generation_id"] == second.generation_id
    assert pointer["latest_complete"]["generation_id"] == first.generation_id
    assert backend.visible(DATES_INDEX_FILENAME) == first_index
    assert second.dates_index_changed is False
    assert second.pointer_changed is True


def test_same_date_revision_replaces_index_head_but_coordinate_is_immutable(tmp_path):
    revision_one = _candidate_directory(tmp_path / "r1")
    revision_two = _candidate_directory(tmp_path / "r2", revision=2)
    conflicting_one = _candidate_directory(
        tmp_path / "conflict", producer_commit="7" * 40
    )
    backend = FakeBackend()
    promote_candidate(
        revision_one,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )

    promoted_two = promote_candidate(
        revision_two,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    index = _json(backend.visible(DATES_INDEX_FILENAME))
    assert index["count"] == 1
    assert index["dates"][0]["generation_revision"] == 2
    assert index["dates"][0]["generation_id"] == promoted_two.generation_id
    prior_head = backend.control_head()

    with pytest.raises(PromotionError, match="already owns"):
        promote_candidate(
            conflicting_one,
            backend,
            execute=True,
            expected_producer_commit="7" * 40,
        )
    assert backend.control_head() == prior_head


def test_exact_retry_is_idempotent_and_creates_no_control_commit(tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = FakeBackend()
    promote_candidate(
        directory,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    prior_head = backend.control_head()
    prior_commit_count = len(backend.commits)

    result = promote_candidate(
        directory,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )

    assert result.pointer_changed is False
    assert result.dates_index_changed is False
    assert result.index_commit is None
    assert result.pointer_commit is None
    assert backend.control_head() == prior_head
    assert len(backend.commits) == prior_commit_count


def test_remote_manifest_corruption_blocks_control_publication(tmp_path):
    first = _candidate_directory(tmp_path / "first")
    second = _candidate_directory(
        tmp_path / "second", observation_date="2026-08-15"
    )
    backend = FakeBackend()
    initial = promote_candidate(
        first,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    prior_head = backend.control_head()
    manifest_name = next(
        name
        for name in backend.list_asset_names(initial.candidate_tag)
        if name.endswith(".json")
    )
    corrupt_url = (
        f"https://github.com/yanniedog/AR-local/releases/download/"
        f"{initial.candidate_tag}/{manifest_name}"
    )
    backend.corrupt_urls.add(corrupt_url)

    with pytest.raises(PromotionError, match="SHA-256"):
        promote_candidate(
            second,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
        )

    assert backend.control_head() == prior_head


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
    assert workflow.count("ref: main") == 2
    assert "timeout-minutes: 60" in workflow
    assert "AR_V3_PROMOTION_APPROVED" in workflow
    assert workflow.count("--verify-candidate-run") == 2
    assert workflow.count("--expected-producer-commit") == 2
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


def test_prepared_pointer_remains_contract_valid_before_control_cas(tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = FakeBackend()
    captured: dict[str, bytes] = {}

    def stop_after_prepare(stage: str) -> None:
        if stage == "after_pointer_written":
            captured["pointer"] = backend.visible(POINTER_FILENAME) or b""

    promote_candidate(
        directory,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
        failure_hook=stop_after_prepare,
    )
    pointer = _json(captured["pointer"])
    bundle = load_candidate(directory)
    validate_generation_pointer(
        pointer,
        {bundle.generation_id: bundle.manifest_bytes},
        {bundle.generation_id: bundle.capability_bytes},
    )
