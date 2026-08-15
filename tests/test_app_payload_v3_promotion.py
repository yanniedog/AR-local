from __future__ import annotations

import hashlib
import json
import urllib.parse
from collections.abc import Mapping, Sequence
from functools import partial
from pathlib import Path

import pytest

import app_payload_v3_github
import app_payload_v3_promotion
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
from app_payload_v3_state import CandidateReleaseRecord
from cdr_domain.contract_validation import contract_sha256
from cdr_domain.generation import GenerationInputs, build_generation_candidate, write_generation_candidate
from cdr_domain.normalize import normalize_product


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "canonical_domain_real_observations.json"
PRODUCER_COMMIT = "6f696ecc3a61198b90ad58f8b90b086e866a26e4"
TRUSTED_RUN_ID = "12345"
promote_candidate = partial(promote_candidate, candidate_run_id=TRUSTED_RUN_ID)


@pytest.fixture(autouse=True)
def _reviewed_consumer_parity_lock(monkeypatch):
    monkeypatch.setattr(
        app_payload_v3_github,
        "AR_APP_CONSUMER_PARITY_LOCK",
        (contract_sha256(), "f" * 64),
    )
    monkeypatch.setattr(
        app_payload_v3_promotion,
        "require_candidate_artifact_binding",
        lambda: None,
    )
    monkeypatch.setattr(
        app_payload_v3_promotion,
        "require_candidate_publication_store",
        lambda: None,
    )


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
    prior: Path | None = None,
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
            "prior_ledger_digest": (
                load_candidate(prior).manifest["ledger_event_digest"]
                if prior is not None
                else None
            ),
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
        self.renew_count = 0
        self.displace_on_renew: int | None = None

    def verify_candidate_artifact(self, run_id: str, candidate) -> str:
        if run_id != TRUSTED_RUN_ID:
            raise PromotionError("unexpected fake candidate run")
        for capability, descriptor in candidate.manifest["capabilities"].items():
            tag = urllib.parse.urlparse(str(descriptor["url"])).path.split(
                "/download/", 1
            )[1].split("/", 1)[0]
            name = f"{descriptor['sha256']}.json.gz"
            release = self.releases.setdefault(
                tag,
                {
                    "metadata": {
                        "title": "AR payload v3 content-addressed assets",
                        "notes": "Append-only content-addressed payload-v3 capability assets.",
                        "target": str(candidate.manifest["producer_commit"]),
                    },
                    "assets": {},
                    "draft": False,
                },
            )
            release["assets"][name] = candidate.capability_bytes[capability]
        return str(candidate.manifest["producer_commit"])

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

    def renew_lock(self, owner_token: str) -> str:
        if self.lock_owner != owner_token:
            raise ConcurrencyError("lock owner changed before renewal")
        self.renew_count += 1
        if self.displace_on_renew == self.renew_count:
            self.lock_owner = "successor"
            raise ConcurrencyError("lock owner changed during renewal")
        self.events.append(("renew", owner_token))
        return "lock-renewed"

    def verify_immutable_asset(self, tag: str, name: str, payload: bytes) -> None:
        release = self.releases.get(tag)
        if release is None or release.get("draft") is not False:
            raise PromotionError("immutable release is absent or unpublished")
        assets = release["assets"]
        assert isinstance(assets, dict)
        if assets.get(name) != payload:
            raise PromotionError("immutable release asset differs")

    def publish_candidate_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
        assets: Mapping[str, bytes],
        owner_token: str,
    ) -> None:
        self.renew_lock(owner_token)
        metadata = {"title": title, "notes": notes, "target": target_commit}
        release = self.releases.get(tag)
        if release is None:
            release = {"metadata": metadata, "assets": {}, "draft": True}
            self.releases[tag] = release
            self.events.append(("draft", tag))
        elif release["metadata"] != metadata:
            raise PromotionError("candidate release metadata differs")
        existing = release["assets"]
        assert isinstance(existing, dict)
        if not set(existing).issubset(assets):
            raise PromotionError("candidate release has unexpected assets")
        if release.get("draft") is False:
            if existing != dict(assets):
                raise PromotionError("published candidate release asset set differs")
            return
        for name, payload in assets.items():
            if self.fail_put_tag == tag:
                raise PromotionError("injected asset backend failure")
            if name in existing and existing[name] != payload:
                raise PromotionError("candidate draft asset differs")
            if name not in existing:
                self.renew_lock(owner_token)
                existing[name] = payload
                self.events.append(("asset", (tag, name)))
        self.renew_lock(owner_token)
        release["draft"] = False
        self.events.append(("publish", tag))

    def verify_candidate_release(
        self,
        tag: str,
        *,
        title: str,
        notes: str,
        target_commit: str,
    ) -> None:
        expected = {"title": title, "notes": notes, "target": target_commit}
        if self.releases[tag]["metadata"] != expected:
            raise PromotionError("immutable release metadata or tag target differs")
        if self.releases[tag].get("draft") is not False:
            raise PromotionError("candidate release is not published")

    def list_candidate_releases(self) -> Sequence[CandidateReleaseRecord]:
        if self.fail_list:
            raise PromotionError("injected complete-listing failure")
        records = []
        for tag, release in self.releases.items():
            if not tag.startswith(CANDIDATE_TAG_PREFIX) or tag in self.omitted_tags:
                continue
            metadata = release["metadata"]
            assets = release["assets"]
            assert isinstance(metadata, dict)
            assert isinstance(assets, dict)
            records.append(
                CandidateReleaseRecord(
                    tag=tag,
                    title=str(metadata["title"]),
                    notes=str(metadata["notes"]),
                    target_commit=str(metadata["target"]),
                    draft=bool(release.get("draft")),
                    prerelease=False,
                    asset_names=tuple(sorted(assets)),
                )
            )
        return sorted(records, key=lambda record: record.tag)

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


def test_remote_bundle_rejects_noncanonical_capability_url_before_asset_fetch(tmp_path):
    candidate = load_candidate(_candidate_directory(tmp_path))
    manifest = json.loads(candidate.manifest_bytes)
    descriptor = next(iter(manifest["capabilities"].values()))
    digest = descriptor["sha256"]
    descriptor["url"] = descriptor["url"].replace(
        f"/{digest}.json.gz", f"/prefix-{digest}.json.gz"
    )
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode() + b"\n"

    class NoncanonicalRemote(FakeBackend):
        def __init__(self) -> None:
            super().__init__()
            self.fetches: list[str] = []

        def fetch_url(self, url: str, _max_bytes: int) -> bytes:
            self.fetches.append(url)
            if len(self.fetches) != 1:
                pytest.fail("noncanonical capability URL must not be fetched")
            return manifest_bytes

    backend = NoncanonicalRemote()
    with pytest.raises(PromotionError, match="filename is not its exact SHA-256"):
        _remote_bundle(backend, "https://example.invalid/manifest.json")
    assert backend.fetches == ["https://example.invalid/manifest.json"]
    assert backend.events == []


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
        tmp_path / "second", observation_date="2026-08-15", prior=first
    )
    backend = FakeBackend()
    promote_candidate(first, backend, execute=True, expected_producer_commit=PRODUCER_COMMIT)
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


def test_disconnected_ledger_successor_cannot_advance_control(tmp_path):
    first = _candidate_directory(tmp_path / "first")
    disconnected = _candidate_directory(
        tmp_path / "disconnected", observation_date="2026-08-15"
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
    event_boundary = len(backend.events)

    with pytest.raises(PromotionError, match="disconnected ledger lineage"):
        promote_candidate(
            disconnected,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
        )

    assert backend.control_head() == prior_head
    assert backend.visible(DATES_INDEX_FILENAME) == prior_index
    assert backend.visible(POINTER_FILENAME) == prior_pointer
    assert load_candidate(disconnected).candidate_tag not in backend.releases
    assert not [
        event
        for event in backend.events[event_boundary:]
        if event[0] in {"draft", "asset", "publish", "prepare", "install"}
    ]


@pytest.mark.parametrize("prior_index_state", ["malformed", "inconsistent"])
def test_invalid_prior_dates_index_fails_before_candidate_or_control_mutation(
    tmp_path, prior_index_state
):
    first = _candidate_directory(tmp_path / "first")
    second = _candidate_directory(
        tmp_path / "second", observation_date="2026-08-15", prior=first
    )
    backend = FakeBackend()
    promote_candidate(
        first,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    prior_head = backend.control_head()
    assert prior_head is not None
    if prior_index_state == "malformed":
        poisoned = b"{"
    else:
        value = _json(backend.visible(DATES_INDEX_FILENAME))
        entry = value["dates"][0]
        entry["observation_date"] = "2026-08-13"
        digest = entry["generation_digest"]
        entry["generation_id"] = f"gen-2026-08-13-r0001-{digest[:12]}"
        entry["manifest_url"] = (
            "https://github.com/yanniedog/AR-local/releases/download/"
            f"{CANDIDATE_TAG_PREFIX}{entry['generation_id']}/"
            f"{entry['manifest_sha256']}.json"
        )
        poisoned = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    backend.commits[prior_head][DATES_INDEX_FILENAME] = poisoned
    event_boundary = len(backend.events)

    with pytest.raises(PromotionError, match="prior complete dates index|cannot drop"):
        promote_candidate(second, backend, execute=True,
                          expected_producer_commit=PRODUCER_COMMIT)

    assert load_candidate(second).candidate_tag not in backend.releases
    assert all(event[0] not in {"draft", "asset", "publish", "prepare", "install"}
               for event in backend.events[event_boundary:])


def test_displaced_owner_is_fenced_before_next_draft_asset_and_retry_resumes(tmp_path):
    directory = _candidate_directory(tmp_path)
    candidate = load_candidate(directory)
    backend = FakeBackend()
    backend.displace_on_renew = 2

    with pytest.raises(ConcurrencyError, match="lock owner changed"):
        promote_candidate(
            directory,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
        )

    draft = backend.releases[candidate.candidate_tag]
    assert draft["draft"] is True
    assert draft["assets"] == {}
    assert backend.control_head() is None
    assert not [event for event in backend.events if event[0] in {"publish", "install"}]

    backend.lock_owner = None
    backend.displace_on_renew = None
    promote_candidate(
        directory,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    assert draft["draft"] is False
    assert set(draft["assets"]) == {candidate.manifest_filename}
    assert backend.control_head() is not None


def test_displaced_owner_is_fenced_before_final_control_cas(tmp_path):
    directory = _candidate_directory(tmp_path)
    backend = FakeBackend()

    def displace_before_cas(stage: str) -> None:
        if stage == "before_pointer_cas":
            backend.lock_owner = "successor"

    with pytest.raises(ConcurrencyError, match="lock owner changed"):
        promote_candidate(
            directory,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
            failure_hook=displace_before_cas,
        )

    assert backend.control_head() is None
    assert not [event for event in backend.events if event[0] == "install"]


def test_retry_after_newer_candidate_upload_advances_from_full_census(tmp_path):
    first = _candidate_directory(tmp_path / "first")
    second = _candidate_directory(
        tmp_path / "second", observation_date="2026-08-15", prior=first
    )
    third = _candidate_directory(
        tmp_path / "third", observation_date="2026-08-16", prior=second
    )
    backend = FakeBackend()
    promote_candidate(
        first,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    prior_head = backend.control_head()

    def crash_after_public_candidate(stage: str) -> None:
        if stage == "after_candidate_verified":
            raise PromotionError("injected crash after candidate verification")

    with pytest.raises(PromotionError, match="injected crash"):
        promote_candidate(
            second,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
            failure_hook=crash_after_public_candidate,
        )
    assert backend.control_head() == prior_head

    promote_candidate(
        third,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    pointer = _json(backend.visible(POINTER_FILENAME))
    index = _json(backend.visible(DATES_INDEX_FILENAME))
    assert pointer["latest_observation"]["generation_id"] == load_candidate(
        third
    ).generation_id
    assert [item["observation_date"] for item in index["dates"]] == [
        "2026-08-14",
        "2026-08-15",
        "2026-08-16",
    ]


def test_historical_candidate_tag_mutation_blocks_every_control_update(tmp_path):
    first = _candidate_directory(tmp_path / "first")
    second = _candidate_directory(
        tmp_path / "second", observation_date="2026-08-15", prior=first
    )
    backend = FakeBackend()
    promoted = promote_candidate(
        first,
        backend,
        execute=True,
        expected_producer_commit=PRODUCER_COMMIT,
    )
    prior_head = backend.control_head()
    metadata = backend.releases[promoted.candidate_tag]["metadata"]
    assert isinstance(metadata, dict)
    metadata["target"] = "7" * 40

    with pytest.raises(PromotionError, match="metadata or tag target differs"):
        promote_candidate(
            second,
            backend,
            execute=True,
            expected_producer_commit=PRODUCER_COMMIT,
        )

    assert backend.control_head() == prior_head


def test_remote_manifest_corruption_blocks_control_publication(tmp_path):
    first = _candidate_directory(tmp_path / "first")
    second = _candidate_directory(
        tmp_path / "second", observation_date="2026-08-15", prior=first
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
