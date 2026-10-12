"""Real retained rates exercise direct delivery without network publication."""
import copy
from pathlib import Path

import pytest

import app_payload_public_companion as companion
from app_payload_public_github import BRANCH, PublicGitHubStore, public_path
from app_payload_revisions_state import RevisionError, canonical, decode_document, digest
from tests.test_app_payload_revisions import MemoryStore, REPO, build_payload, publish


class PublicMemory:
    def __init__(self):
        self.current = None
        self.commits = {}
        self.promotions = 0
        self.fail_staged = False
        self.race = False

    def snapshot(self):
        files = self.commits.get(self.current, {})
        return self.current, self.current, {path: digest(raw) for path, raw in files.items()}

    def read(self, ref, path, limit):
        selected = self.current if ref == BRANCH else ref
        raw = self.commits[selected][path]
        if self.fail_staged and selected != self.current:
            return b"corrupt"
        if len(raw) > limit:
            raise RevisionError("byte limit")
        return raw

    def stage(self, head, tree, files):
        content = {**self.commits.get(head, {}), **files}
        commit = digest(canonical({key: digest(value) for key, value in content.items()}))[:40]
        self.commits[commit] = content
        return commit

    def promote(self, old, new):
        if self.race or self.current != old:
            raise RevisionError("predecessor changed")
        self.current = new
        self.promotions += 1


class AuthenticatedMemory(MemoryStore):
    def read(self, tag, name, limit=8 * 1024 * 1024, *, require_encrypted=False):
        if require_encrypted and getattr(self, "plaintext", False):
            from release_transport import PlaintextTransportError
            raise PlaintextTransportError("Unauthenticated plaintext")
        return super().read(tag, name, limit)


@pytest.fixture
def editions(tmp_path, monkeypatch):
    monkeypatch.setattr("app_payload_public_bootstrap.REPO", REPO)
    store = AuthenticatedMemory()
    store.repo, store.gh = REPO, "gh"
    real_publish = companion.publish_companion
    monkeypatch.setattr(companion, "publish_companion", lambda *_: None)

    def create(name="first", marker=True, **options):
        root = tmp_path / name
        manifest = build_payload(root / "payload", **options)
        if marker:
            manifest["delivery"] = companion.MODE
        (root / "payload/manifest.json").write_bytes(canonical(manifest))
        result = publish(root, store)
        return result.archive_dir
    return create, store, real_publish


def test_atomic_public_inventory_keeps_original_receipts_and_private_releases(editions, tmp_path):
    create, store, mirror = editions
    archive = create()
    private = copy.deepcopy(store.objects)
    public = PublicMemory()
    mirror(archive, store, tmp_path / "receipts", public_store=public)
    manifest = decode_document((archive / "manifest.json").read_bytes())
    files = public.commits[public.current]
    assert files["latest/manifest.json"] == (archive / "manifest.json").read_bytes()
    assert files["latest/dates-index.json"] == store.read("app-payload-latest", "dates-index.json")
    assert set(files) == {"latest/manifest.json", "latest/dates-index.json", f'tags/{manifest["tag"]}/manifest.json',
                          *[f'tags/{manifest["tag"]}/{entry["name"]}' for entry in manifest["files"].values()]}
    assert store.objects == private
    mirror(archive, store, tmp_path / "receipts", public_store=public)
    assert public.promotions == 1


@pytest.mark.parametrize("failure", ["readback", "race"])
def test_partial_staging_never_changes_either_selector(editions, tmp_path, failure):
    create, store, mirror = editions
    public = PublicMemory()
    mirror(create(omit_last_product=True), store, tmp_path / "receipts", public_store=public)
    before = public.current
    second = create("second", generated_at="2026-05-19T05:00:00Z")
    public.fail_staged = failure == "readback"
    public.race = failure == "race"
    with pytest.raises(RevisionError):
        mirror(second, store, tmp_path / "receipts", public_store=public)
    assert public.current == before
    public.fail_staged = public.race = False
    mirror(second, store, tmp_path / "receipts", public_store=public)
    assert public.current != before
    assert all(path in public.commits[public.current] for path in public.commits[before])


def test_immutable_collision_and_regression_refuse_promotion(editions, tmp_path):
    create, store, mirror = editions
    archive = create()
    public = PublicMemory()
    mirror(archive, store, tmp_path / "receipts", public_store=public)
    immutable = next(path for path in public.commits[public.current] if path.startswith("tags/") and path.endswith(".gz"))
    public.commits[public.current][immutable] = b"wrong"
    with pytest.raises(RevisionError, match="collision"):
        mirror(archive, store, tmp_path / "receipts", public_store=public)
    assert public.promotions == 1


def test_bootstrap_requires_existing_selected_exact_authenticated_bytes(editions, tmp_path):
    create, store, mirror = editions
    archive = create(marker=False)
    public = PublicMemory()
    with pytest.raises(RevisionError, match="direct-delivery"):
        mirror(archive, store, tmp_path / "receipts", public_store=public)
    mirror(archive, store, tmp_path / "receipts", public_store=public, bootstrap=True)
    manifest = decode_document((archive / "manifest.json").read_bytes())
    store.objects[(manifest["tag"], "manifest.json")] = b"wrong transport domain"
    with pytest.raises(RevisionError, match="authenticated"):
        mirror(archive, store, tmp_path / "receipts", public_store=public, bootstrap=True)


def test_bootstrap_refuses_plaintext_transport_even_when_domain_receipts_match(editions, tmp_path):
    create, store, mirror = editions
    archive = create(marker=False)
    store.plaintext = True
    public = PublicMemory()
    with pytest.raises(Exception, match="Unauthenticated plaintext"):
        mirror(archive, store, tmp_path / "receipts", public_store=public, bootstrap=True)
    assert not public.commits


@pytest.mark.parametrize("private", ["preservation.json", "source-manifest.json", "base-manifest.json", "revision-delta.json", "publication-provenance.json", "execution.jsonl"])
def test_private_objects_cannot_be_addressed_or_uploaded(private):
    assert not public_path(f"tags/app-payload-2026-05-19-r000001/{private}")
    store = PublicGitHubStore(REPO)
    with pytest.raises(RevisionError, match="Private"):
        store.stage(None, None, {f"tags/app-payload-2026-05-19-r000001/{private}": b"{}"})


def test_stage_rejects_ciphertext_before_api_use():
    store = PublicGitHubStore(REPO)
    with pytest.raises(RevisionError, match="encrypted"):
        store.stage(None, None, {"tags/app-payload-2026-05-19-r000001/manifest.json": b"ARE1secret"})


def test_public_ref_update_is_never_forced(monkeypatch):
    store = PublicGitHubStore(REPO)
    heads = iter(["a" * 40, "b" * 40])
    monkeypatch.setattr(store, "head", lambda: next(heads))
    calls = []
    monkeypatch.setattr(store, "api", lambda *args, **kwargs: calls.append((args, kwargs)))
    store.promote("a" * 40, "b" * 40)
    assert calls == [(("PATCH", f"git/refs/heads/{BRANCH}", {"sha": "b" * 40, "force": False}), {})]


def test_bootstrap_prepare_authenticates_are2_and_preserves_domain_bytes(editions, tmp_path, monkeypatch):
    from app_payload_public_bootstrap import prepare
    from app_payload_revisions_github import GitHubRevisionStore
    from release_transport import encrypt_transport, PlaintextTransportError
    import app_payload_secure_upload
    create, memory, _ = editions
    archive = create(marker=False)
    key = bytes(range(32))
    monkeypatch.setattr(app_payload_secure_upload, "resolve_release_key", lambda _: key)
    reader = GitHubRevisionStore(REPO, gh="gh")
    wires = {f"https://github.com/{REPO}/releases/download/{tag}/{name}": encrypt_transport(raw, key)
             for (tag, name), raw in memory.objects.items()}
    monkeypatch.setattr(reader, "read_wire_url", lambda url, limit: wires.get(url))
    raw = (archive / "manifest.json").read_bytes()
    destination = tmp_path / "prepared"
    result = prepare(reader, destination, digest(raw))
    assert (destination / "manifest.json").read_bytes() == raw
    for entry in result["files"].values():
        assert (destination / entry["name"]).read_bytes() == (archive / entry["name"]).read_bytes()
    wires[reader.url(result["tag"], "manifest.json")] = raw
    with pytest.raises(PlaintextTransportError):
        prepare(reader, tmp_path / "plaintext", digest(raw))


@pytest.mark.parametrize("field", ["bundle_sha256", "generation_id"])
def test_bootstrap_rejects_inconsistent_revision_binding(editions, tmp_path, field):
    from app_payload_public_bootstrap import prepare
    create, store, _ = editions
    archive = create(marker=False)
    manifest = decode_document((archive / "manifest.json").read_bytes())
    manifest["payload_revision"][field] = "0" * 64
    raw = canonical(manifest)
    index = decode_document(store.read("app-payload-latest", "dates-index.json"))
    index["revision_heads"][manifest["run_date"]]["manifest_sha256"] = digest(raw)
    store.objects[(manifest["tag"], "manifest.json")] = raw
    store.objects[("app-payload-latest", "dates-index.json")] = canonical(index)
    with pytest.raises(RevisionError, match="selected canonical revision"):
        prepare(store, tmp_path / "invalid", digest(raw))


def test_bootstrap_refuses_unreviewed_head_and_wrong_asset_receipt(editions, tmp_path):
    from app_payload_public_bootstrap import prepare
    create, store, _ = editions
    archive = create(marker=False)
    raw = (archive / "manifest.json").read_bytes()
    manifest = decode_document(raw)
    with pytest.raises(RevisionError, match="reviewed bootstrap identity"):
        prepare(store, tmp_path / "wrong-head", "0" * 64)
    entry = next(iter(manifest["files"].values()))
    store.objects[(manifest["tag"], entry["name"])] = b"wrong"
    with pytest.raises(RevisionError, match="asset receipt"):
        prepare(store, tmp_path / "wrong-asset", digest(raw))


def test_bootstrap_index_race_cannot_promote(editions, tmp_path):
    create, store, mirror = editions
    archive = create(marker=False)
    public = PublicMemory()
    original = public.stage
    def stage(*args):
        commit = original(*args)
        store.objects[("app-payload-latest", "dates-index.json")] += b" "
        return commit
    public.stage = stage
    with pytest.raises(RevisionError, match="selection changed"):
        mirror(archive, store, tmp_path / "receipts", public_store=public, bootstrap=True)
    assert public.current is None


@pytest.mark.parametrize("mutation", ["inner_are1", "private_descriptor"])
def test_bootstrap_inventory_refuses_private_or_inner_encrypted_assets(editions, mutation):
    create, _, _ = editions
    archive = create(marker=False)
    manifest = decode_document((archive / "manifest.json").read_bytes())
    entry = next(iter(manifest["files"].values()))
    if mutation == "inner_are1":
        raw = b"ARE1private-inner-ciphertext"
    else:
        entry["name"] = "preservation.json"
        raw = b"{}"
    entry["bytes"], entry["sha256"] = len(raw), digest(raw)
    (archive / entry["name"]).write_bytes(raw)
    with pytest.raises(RevisionError):
        companion._inventory(archive, manifest, bootstrap=True)
