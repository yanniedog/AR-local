"""Protocol faults use retained real CDR products/rates, never acceptance demo data."""
from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app_payload_common import DEFAULT_TAG
from app_payload_revisions import publish_revision_bundle, revision_mode_enabled
from app_payload_revisions_github import GitHubRevisionStore
from app_payload_revisions_state import (
    RevisionError, bundle_sha256, canonical, decode_document, digest, validate_manifest,
)

FIXTURES = Path(__file__).parent / "fixtures"
CONSUMER = "a" * 40
REPO = "owner/repository"
DAY = "2026-05-19"


class MemoryStore:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.fail_asset: str | None = None
        self.change_index_before_replace = False
        self.promotions = 0

    def url(self, tag, name):
        return f"https://github.com/{REPO}/releases/download/{tag}/{name}"

    def read(self, tag, name, limit=8 * 1024 * 1024):
        raw = self.objects.get((tag, name))
        if raw is not None and len(raw) > limit:
            raise RevisionError("response exceeds budget")
        return raw

    def read_url(self, url, limit=64 * 1024 * 1024):
        prefix = f"https://github.com/{REPO}/releases/download/"
        assert url.startswith(prefix)
        tag, name = url[len(prefix):].split("/", 1)
        return self.read(tag, name, limit)

    def tags(self):
        return sorted({tag for tag, _ in self.objects})

    def archive(self, tag, paths):
        for path in paths:
            if path.name == self.fail_asset:
                raise RevisionError("interrupted upload")
            raw = path.read_bytes()
            key = (tag, path.name)
            if key in self.objects and self.objects[key] != raw:
                raise RevisionError("immutable release collision")
            self.objects[key] = raw

    def replace_index(self, tag, path, expected):
        if self.change_index_before_replace:
            self.objects[(tag, "dates-index.json")] = b'{"external":"writer"}'
        if self.read(tag, "dates-index.json") != expected:
            raise RevisionError("stale publisher")
        self.objects[(tag, "dates-index.json")] = path.read_bytes()
        self.promotions += 1

    def restore_missing_index(self, tag, path):
        assert self.read(tag, "dates-index.json") is None
        self.objects[(tag, "dates-index.json")] = path.read_bytes()


def build_payload(root: Path, *, omit_last_product=False, omit_last_rate=False,
                  generated_at="2026-05-19T04:00:00Z", optional=False):
    retained = json.loads((FIXTURES / "product_facts_real_2026-05-19.json").read_text())
    facts = retained["products"][:-1] if omit_last_product else retained["products"]
    products = {f"{item['provider']}|{item['record']['productId']}": item["record"]
                for item in facts}
    rates = json.loads((FIXTURES / "bank_spread_rows_2026-05-19.json").read_text())["rates"]
    if omit_last_rate:
        rates = rates[:-1]
    documents = {
        "core": {"schema_version": 1, "run_date": DAY,
                 "sections": {"Mortgage": {"rates": rates}}},
        "details": {"schema_version": 1, "run_date": DAY, "products": products},
    }
    if optional:
        documents["search_index"] = {"schema_version": 1, "products": products}
    root.mkdir(parents=True, exist_ok=True)
    files = {}
    for key, value in documents.items():
        raw = gzip.compress(canonical(value), mtime=0)
        name = f"{key}-{DAY}-{digest(raw)[:12]}.json.gz"
        (root / name).write_bytes(raw)
        files[key] = {"name": name, "bytes": len(raw), "sha256": digest(raw),
                      "url": f"https://github.com/{REPO}/releases/download/{DEFAULT_TAG}/{name}"}
    manifest = {"schema_version": 1, "run_date": DAY, "generated_at": generated_at,
                "repo": REPO, "tag": DEFAULT_TAG, "files": files}
    (root / "manifest.json").write_bytes(canonical(manifest))
    return manifest


def publish(root, store, payload=None):
    return publish_revision_bundle(payload or root / "payload", state_dir=root / "state",
                                   repo=REPO, enabled=True, consumer_commit=CONSUMER, store=store)


def test_initial_and_details_only_revisions_preserve_all_bytes(tmp_path):
    store = MemoryStore()
    first_manifest = build_payload(tmp_path / "payload", omit_last_product=True)
    first = publish(tmp_path, store)
    retained = dict(store.objects)
    second_manifest = build_payload(tmp_path / "next", generated_at="2026-05-19T05:00:00Z")
    assert first_manifest["files"]["core"] == second_manifest["files"]["core"]
    second = publish(tmp_path, store, tmp_path / "next")
    assert first.head["revision"] == 1
    assert second.head["revision"] == 2
    assert second.manifest["payload_revision"]["parent_revision"] == 1
    assert second.head["bundle_sha256"] != first.head["bundle_sha256"]
    for key, value in retained.items():
        if key != (DEFAULT_TAG, "dates-index.json"):
            assert store.objects[key] == value
    delta = decode_document((second.archive_dir / "revision-delta.json").read_bytes())
    assert len(delta["products"]["added"]) == 1
    assert delta["rate_rows"] == {"added": {}, "removed": {}}
    assert delta["assets_changed"] == ["details"]


def test_optional_only_revision_changes_identity(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload")
    first = publish(tmp_path, store)
    build_payload(tmp_path / "optional", optional=True)
    second = publish(tmp_path, store, tmp_path / "optional")
    assert second.head["revision"] == first.head["revision"] + 1
    assert "search_index" in second.manifest["files"]


def test_source_observation_changes_revision_even_when_assets_match(tmp_path):
    store = MemoryStore()
    original = build_payload(tmp_path / "payload")
    first = publish(tmp_path, store)
    next_manifest = build_payload(tmp_path / "next")
    # Pure provenance metadata binds a recapture without fabricating rate data.
    next_manifest["source_observation"] = {
        "generation_id": "obs-2026-05-19-recapture",
        "contract_digest": "b" * 64, "event_digest": "c" * 64,
    }
    (tmp_path / "next" / "manifest.json").write_bytes(canonical(next_manifest))
    assert original["files"] == next_manifest["files"]
    second = publish(tmp_path, store, tmp_path / "next")
    assert second.head["revision"] == first.head["revision"] + 1
    assert second.head["bundle_sha256"] != first.head["bundle_sha256"]
    delta = decode_document((second.archive_dir / "revision-delta.json").read_bytes())
    assert delta["assets_changed"] == []


def test_dual_build_promotes_full_revision_before_compatibility_aliases(tmp_path, monkeypatch):
    import app_payload
    import app_payload_build
    import app_payload_revisions

    retained = build_payload(tmp_path / "retained", optional=True)
    documents = {key: json.loads(gzip.decompress((tmp_path / "retained" / entry["name"]).read_bytes()))
                 for key, entry in retained["files"].items()}
    data = {**documents, "run_date": DAY, "counts": {}, "history_banks": None,
            "bank_history": None, "bank_spread_history": None, "rba_calendar": None}
    exports = tmp_path / "exports"
    (exports / "dashboard-cache").mkdir(parents=True)
    (exports / "dashboard-cache" / "latest.json").write_bytes(canonical({"run_date": DAY}))
    store = MemoryStore()
    calls = []

    def compute(*args, **kwargs):
        assert kwargs["include_history"] is True
        return copy.deepcopy(data)

    def revision(directory, **kwargs):
        return publish_revision_bundle(directory, **kwargs, store=store)

    def alias(directory, *, repo, tag):
        assert store.promotions == 1
        manifest = decode_document((directory / "manifest.json").read_bytes())
        assert manifest["payload_revision"]["revision"] == 1
        assert "search_index" in manifest["files"]
        assert all("-r000001/" in item["url"] for item in manifest["files"].values())
        calls.append(tag)
        return True

    monkeypatch.setenv("AR_LOCAL_PAYLOAD_REVISIONS", "1")
    monkeypatch.setenv("AR_APP_REVISION_CONSUMER_SHA", CONSUMER)
    monkeypatch.setattr(app_payload, "_live_manifest_status", lambda *args: ("missing", None))
    monkeypatch.setattr(app_payload, "_compute_payload", compute)
    monkeypatch.setattr(app_payload_revisions, "publish_revision_bundle", revision)
    monkeypatch.setattr(app_payload_build, "publish_payload", alias)
    provenance = {"generation_id": "retained-observation", "contract_digest": "d" * 64}
    manifest, dated, latest = app_payload_build.build_and_publish_dual(
        exports, repo=REPO, state_dir=tmp_path / "persistent", source_observation=provenance,
    )
    assert manifest["source_observation"] == provenance
    assert dated is True and latest is True
    assert calls == [f"app-payload-{DAY}", DEFAULT_TAG]


def test_return_to_previous_bundle_creates_new_revision_with_current_parent(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload")
    first = publish(tmp_path, store)
    build_payload(tmp_path / "next", optional=True, generated_at="2026-05-19T05:00:00Z")
    second = publish(tmp_path, store, tmp_path / "next")
    build_payload(tmp_path / "restored", generated_at="2026-05-19T06:00:00Z")
    restored = publish(tmp_path, store, tmp_path / "restored")
    assert restored.head["revision"] == 3
    assert restored.head["bundle_sha256"] == first.head["bundle_sha256"]
    assert restored.manifest["payload_revision"]["parent_revision"] == second.head["revision"]


def test_timestamp_and_alias_only_rebuild_is_idempotent(tmp_path):
    store = MemoryStore()
    original = build_payload(tmp_path / "payload")
    first = publish(tmp_path, store)
    manifest = build_payload(tmp_path / "next", generated_at="2026-05-19T06:00:00Z")
    manifest["tag"] = "different-alias"
    manifest["files"]["core"]["url"] = "https://github.com/unused/url"
    (tmp_path / "next" / "manifest.json").write_bytes(canonical(manifest))
    assert bundle_sha256(original) == bundle_sha256(manifest)
    repeated = publish(tmp_path, store, tmp_path / "next")
    assert repeated.head == first.head
    assert repeated.index_changed is False
    assert store.promotions == 1


def test_interrupted_archive_cannot_advance_head_and_retry_reuses_reservation(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload")
    store.fail_asset = "manifest.json"
    with pytest.raises(RevisionError, match="interrupted"):
        publish(tmp_path, store)
    assert store.read(DEFAULT_TAG, "dates-index.json") is None
    store.fail_asset = None
    build_payload(tmp_path / "payload", generated_at="2026-05-19T05:00:00Z")
    result = publish(tmp_path, store)
    assert result.head["revision"] == 1
    assert len(list((tmp_path / "state" / "revisions" / DAY).glob("r*/reservation.json"))) == 1


def test_abandoned_older_reservation_cannot_supersede_newer_selected_revision(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload", omit_last_product=True)
    store.fail_asset = "manifest.json"
    with pytest.raises(RevisionError):
        publish(tmp_path, store)
    store.fail_asset = None
    build_payload(tmp_path / "newer", generated_at="2026-05-19T05:00:00Z")
    current = publish(tmp_path, store, tmp_path / "newer")
    assert current.head["revision"] == 2
    with pytest.raises(RevisionError, match="stale publisher"):
        publish(tmp_path, store)
    assert store.promotions == 1


def test_concurrent_pointer_change_is_not_overwritten(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload")
    store.change_index_before_replace = True
    with pytest.raises(RevisionError, match="stale publisher"):
        publish(tmp_path, store)
    assert store.read(DEFAULT_TAG, "dates-index.json") == b'{"external":"writer"}'
    assert store.read(f"app-payload-{DAY}-r000001", "manifest.json") is not None


def test_killed_index_replacement_restores_predecessor_and_completes_retry(tmp_path, monkeypatch):
    store = MemoryStore()
    build_payload(tmp_path / "payload")
    publish(tmp_path, store)
    build_payload(tmp_path / "next", optional=True)
    replace = store.replace_index

    def killed_after_delete(tag, path, expected):
        del store.objects[(tag, "dates-index.json")]
        raise SystemExit("killed while replacing index")

    monkeypatch.setattr(store, "replace_index", killed_after_delete)
    with pytest.raises(SystemExit):
        publish(tmp_path, store, tmp_path / "next")
    monkeypatch.setattr(store, "replace_index", replace)
    resumed = publish(tmp_path, store, tmp_path / "next")
    assert resumed.head["revision"] == 2
    assert store.promotions == 2


def test_missing_committed_index_restores_selected_revision_without_downgrade(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload")
    publish(tmp_path, store)
    build_payload(tmp_path / "next", optional=True)
    second = publish(tmp_path, store, tmp_path / "next")
    selected = store.objects.pop((DEFAULT_TAG, "dates-index.json"))
    resumed = publish(tmp_path, store, tmp_path / "next")
    assert resumed.head == second.head
    assert resumed.index_changed is False
    assert store.read(DEFAULT_TAG, "dates-index.json") == selected


def test_remote_abandoned_revisions_are_never_reused(tmp_path):
    store = MemoryStore()
    store.objects[(f"app-payload-{DAY}-r000042", "partial.json")] = b"partial"
    build_payload(tmp_path / "payload")
    result = publish(tmp_path, store)
    assert result.head["revision"] == 43


def test_legacy_manifest_raw_bytes_and_full_assets_preserved_before_head(tmp_path):
    store = MemoryStore()
    old = build_payload(tmp_path / "legacy", omit_last_rate=True)
    raw = json.dumps(old, indent=4).encode() + b"\n"
    store.objects[(DEFAULT_TAG, "manifest.json")] = raw
    for entry in old["files"].values():
        store.objects[(DEFAULT_TAG, entry["name"])] = (tmp_path / "legacy" / entry["name"]).read_bytes()
    build_payload(tmp_path / "payload")
    result = publish(tmp_path, store)
    tags = [tag for tag in store.tags() if "-legacy-" in tag]
    assert len(tags) == 1
    assert store.read(tags[0], "source-manifest.json") == raw
    for entry in old["files"].values():
        assert store.read(tags[0], entry["name"]) == store.read(DEFAULT_TAG, entry["name"])
    delta = decode_document((result.archive_dir / "revision-delta.json").read_bytes())
    assert sum(delta["rate_rows"]["added"].values()) == 1


def test_unavailable_legacy_asset_blocks_alias_and_pointer_mutation(tmp_path):
    store = MemoryStore()
    old = build_payload(tmp_path / "old")
    store.objects[(DEFAULT_TAG, "manifest.json")] = canonical(old)
    build_payload(tmp_path / "payload")
    with pytest.raises(RevisionError, match="source asset"):
        publish(tmp_path, store)
    assert store.read(DEFAULT_TAG, "dates-index.json") is None
    assert store.read(DEFAULT_TAG, "manifest.json") == canonical(old)


def test_existing_dates_and_metadata_survive_pointer_promotion(tmp_path):
    store = MemoryStore()
    old = {"schema_version": 1, "dates": ["2026-05-18"], "count": 1,
           "min_date": "2026-05-18", "latest_date": "2026-05-18", "future_metadata": "keep"}
    store.objects[(DEFAULT_TAG, "dates-index.json")] = canonical(old)
    build_payload(tmp_path / "payload")
    publish(tmp_path, store)
    updated = decode_document(store.read(DEFAULT_TAG, "dates-index.json"))
    assert updated["dates"] == ["2026-05-18", DAY]
    assert updated["future_metadata"] == "keep"


def test_corrupt_selected_manifest_holds_installed_head(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload")
    first = publish(tmp_path, store)
    index = store.read(DEFAULT_TAG, "dates-index.json")
    store.objects[(first.manifest["tag"], "manifest.json")] = b"{}"
    build_payload(tmp_path / "next", omit_last_product=True)
    with pytest.raises(RevisionError, match="manifest hash"):
        publish(tmp_path, store, tmp_path / "next")
    assert store.read(DEFAULT_TAG, "dates-index.json") == index


def test_corrupt_selected_optional_asset_blocks_promotion(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload", optional=True)
    first = publish(tmp_path, store)
    index = store.read(DEFAULT_TAG, "dates-index.json")
    entry = first.manifest["files"]["search_index"]
    store.objects[(first.manifest["tag"], entry["name"])] = b"corrupted"
    build_payload(tmp_path / "next")
    with pytest.raises(RevisionError, match="source asset"):
        publish(tmp_path, store, tmp_path / "next")
    assert store.read(DEFAULT_TAG, "dates-index.json") == index


def test_manifest_asset_run_date_mismatch_blocks_promotion(tmp_path):
    store = MemoryStore()
    manifest = build_payload(tmp_path / "payload")
    manifest["run_date"] = "2026-05-20"
    (tmp_path / "payload" / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(RevisionError, match="run_date"):
        publish(tmp_path, store)
    assert store.read(DEFAULT_TAG, "dates-index.json") is None


def test_same_revision_remote_collision_does_not_clobber(tmp_path):
    store = MemoryStore()
    build_payload(tmp_path / "payload")
    store.fail_asset = "manifest.json"
    with pytest.raises(RevisionError):
        publish(tmp_path, store)
    store.fail_asset = None
    store.objects[(f"app-payload-{DAY}-r000001", "manifest.json")] = b"collision"
    with pytest.raises(RevisionError, match="collision"):
        publish(tmp_path, store)
    assert store.read(f"app-payload-{DAY}-r000001", "manifest.json") == b"collision"
    assert store.promotions == 0


def test_explicit_activation_and_shipped_consumer_required(tmp_path, monkeypatch):
    build_payload(tmp_path / "payload")
    monkeypatch.delenv("AR_LOCAL_PAYLOAD_REVISIONS", raising=False)
    monkeypatch.delenv("AR_APP_REVISION_CONSUMER_SHA", raising=False)
    assert revision_mode_enabled() is False
    with pytest.raises(RevisionError, match="disabled"):
        publish_revision_bundle(tmp_path / "payload", state_dir=tmp_path / "state")
    with pytest.raises(RevisionError, match="consumer"):
        publish_revision_bundle(tmp_path / "payload", state_dir=tmp_path / "state", enabled=True)
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("mutation", ["traversal", "hash", "bytes", "duplicate"])
def test_invalid_asset_fails_before_network(tmp_path, mutation):
    manifest = build_payload(tmp_path / "payload")
    if mutation == "traversal":
        manifest["files"]["core"]["name"] = "../escape.json.gz"
    elif mutation == "hash":
        manifest["files"]["core"]["sha256"] = "0" * 64
    elif mutation == "bytes":
        manifest["files"]["core"]["bytes"] = 99_999_999
    else:
        manifest["files"]["details"] = copy.deepcopy(manifest["files"]["core"])
    with pytest.raises(RevisionError):
        validate_manifest(manifest, tmp_path / "payload")


def test_backend_rejects_corrupt_download_after_successful_upload(tmp_path, monkeypatch):
    store = GitHubRevisionStore(REPO, gh="gh")
    asset = tmp_path / "core.json.gz"
    asset.write_bytes(b"compressed test transport bytes")
    monkeypatch.setattr(store, "ensure_release", lambda _: None)
    monkeypatch.setattr(store, "_run", lambda _: SimpleNamespace(returncode=0))
    reads = iter([None, b"corrupted"])
    monkeypatch.setattr(store, "read", lambda *args: next(reads))
    with pytest.raises(RevisionError, match="verification"):
        store.archive("revision-test", [asset])


def test_backend_uncertain_upload_accepts_only_exact_public_bytes(tmp_path, monkeypatch):
    store = GitHubRevisionStore(REPO, gh="gh")
    asset = tmp_path / "transport.json.gz"
    asset.write_bytes(b"protocol transport fixture")
    monkeypatch.setattr(store, "ensure_release", lambda _: None)
    monkeypatch.setattr(store, "_run", lambda _: (_ for _ in ()).throw(RevisionError("timeout")))
    reads = iter([None, asset.read_bytes()])
    monkeypatch.setattr(store, "read", lambda *args: next(reads))
    store.archive("revision-test", [asset])


def test_backend_restores_exact_index_after_interrupted_clobber(tmp_path, monkeypatch):
    store = GitHubRevisionStore(REPO, gh="gh")
    path = tmp_path / "dates-index.json"
    path.write_bytes(b"new")
    reads = iter([b"original exact bytes", None])
    monkeypatch.setattr(store, "read", lambda *args: next(reads))
    calls = []

    def run(args):
        calls.append(args)
        if "--clobber" in args:
            raise RevisionError("interrupted replacement")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(store, "_run", run)
    with pytest.raises(RevisionError, match="interrupted"):
        store.replace_index(DEFAULT_TAG, path, b"original exact bytes")
    assert (tmp_path / "restore" / "dates-index.json").read_bytes() == b"original exact bytes"
    assert "--clobber" not in calls[-1]


def test_backend_rejects_untrusted_initial_urls():
    store = GitHubRevisionStore(REPO, gh="gh")
    with pytest.raises(RevisionError, match="URL"):
        store.read_url("http://127.0.0.1:3111/private")


def test_public_readback_bypasses_stale_github_redirects(monkeypatch):
    import io
    import urllib.request

    requests = []

    def opened(request, timeout):
        requests.append(request.full_url)
        result = io.BytesIO(b"exact bytes")
        result.headers = {}
        return result

    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: SimpleNamespace(open=opened))
    store = GitHubRevisionStore(REPO, gh="gh")
    assert store.read(DEFAULT_TAG, "dates-index.json") == b"exact bytes"
    assert "dates-index.json?_=" in requests[0]


def test_legacy_publisher_cannot_prune_or_overwrite_revision_archives(tmp_path, monkeypatch):
    import app_payload

    build_payload(tmp_path / "payload")
    tag = f"app-payload-{DAY}-r000001"
    assert app_payload._prune_release_assets("gh", REPO, tag, set()) == 0
    with pytest.raises(RuntimeError, match="coordinator"):
        app_payload.publish_payload(tmp_path / "payload", tag=tag)
    monkeypatch.setenv("AR_LOCAL_PAYLOAD_REVISIONS", "1")
    with pytest.raises(RuntimeError, match="unversioned"):
        app_payload.publish_payload(tmp_path / "payload")
    assert app_payload.refresh_dates_index(tmp_path) is False


def test_legacy_refresh_preserves_adopted_heads_when_flag_is_absent(tmp_path, monkeypatch):
    import app_payload

    monkeypatch.delenv("AR_LOCAL_PAYLOAD_REVISIONS", raising=False)
    monkeypatch.setattr(app_payload, "_gh_available", lambda: "gh")
    monkeypatch.setattr(app_payload, "_gh_authed", lambda _: True)
    monkeypatch.setattr(GitHubRevisionStore, "read", lambda *args: canonical({"revision_protocol": 1}))
    assert app_payload.refresh_dates_index(tmp_path) is False
    assert not (tmp_path / ".dates-index").exists()


def test_revision_alias_order_and_protocol_cannot_downgrade():
    from app_payload_publish import _manifest_should_replace

    live = {"run_date": DAY, "generated_at": "2026-05-19T09:00:00Z",
            "payload_revision": {"revision": 2, "generation_id": "current"}}
    options = {"our_run_date": DAY, "our_gen": "2026-05-19T04:00:00Z",
               "tag": DEFAULT_TAG, "force": True}
    assert _manifest_should_replace("present", live, **options) == (False, "revision_protocol_downgrade")
    assert _manifest_should_replace("present", live, **options,
                                    our_revision={"revision": 1}) == (False, "live_newer")
    assert _manifest_should_replace("present", live, **options,
                                    our_revision={"revision": 3}) == (True, "revision")
    assert _manifest_should_replace("present", live, **options,
                                    our_revision={"revision": 2}) == (False, "revision_identity_collision")
