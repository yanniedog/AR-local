import copy
import json
import os
import subprocess
import gzip
import stat
from datetime import date, timedelta
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import pytest

import app_payload_observed as p
from app_payload_secure_upload import secure_upload
from release_transport import PlaintextTransportError, MAGIC, decrypt_transport
from tests.test_app_payload_revisions import build_payload

# Portable protocol tests use retained real May19 financial bytes. They are not
# source-membership or consumer-adoption acceptance. Optional private R2 mode
# binds the separately accepted actual Nov3 candidate, never checked into Git.
PRIVATE_FIXTURE = os.environ.get("AR_OBSERVED_PUBLICATION_FIXTURE")
DAY = "2026-11-03" if PRIVATE_FIXTURE else "2026-05-19"
PREVIOUS_DAY = (date.fromisoformat(DAY) - timedelta(days=1)).isoformat()
R2_MANIFEST_SHA = "1e171689f3e0a3492ed748ffcd41b31fe79c3f33c94051120190cf6aa8767281"
R2_INDEX_SHA = "ed3a14dd5599c19ab9fa303c64034dfd258e89633ef58dc2f9cb7305509299b5"


def retained_protocol_candidate(out):
    m = build_payload(out)
    core = json.loads(gzip.decompress((out / m["files"]["core"]["name"]).read_bytes()))
    details = json.loads(gzip.decompress((out / m["files"]["details"]["name"]).read_bytes()))
    m.update(repo=p.REPO, tag=p.edition(DAY, 2), consumer_contract=p.CHANNEL,
             app_min_version="1.0.0", schedule={"label": "01:00 Australia/Hobart daily",
                                               "next_due_utc": "2026-05-19T15:00:00Z"},
             counts={"products": len(details["products"]),
                     "rates": len(core["sections"]["Mortgage"]["rates"])},
             source_observation={"observation_date": DAY, "observation_state": "partial",
                                 "generation_id": "retained-protocol-fixture-2026-05-19",
                                 "contract_digest": p.digest(p.canonical(m))})
    for f in m["files"].values():
        f["url"] = p.url(m["tag"], f["name"])
    bundle = p.bundle_sha256(m)
    m["payload_revision"] = {"schema_version": 1, "revision": 2, "parent_revision": 1,
                             "bundle_sha256": bundle, "generation_id": "sha256-" + bundle}
    raw = p.canonical(m)
    head = {"revision": 2, "bundle_sha256": bundle, "generation_id": "sha256-" + bundle,
            "manifest_sha256": p.digest(raw), "manifest_url": p.url(m["tag"], "manifest.json")}
    ix = {"schema_version": 1, "revision_protocol": 1, "channel": p.CHANNEL,
          "dates": [DAY], "count": 1, "min_date": DAY, "latest_date": DAY,
          "revision_heads": {DAY: head}}
    (out / "manifest.json").write_bytes(raw)
    (out / "dates-index.json").write_bytes(p.canonical(ix))


@pytest.fixture
def candidate(tmp_path):
    out = tmp_path / "candidate"
    if not PRIVATE_FIXTURE:
        retained_protocol_candidate(out)
        return out
    fixture = Path(PRIVATE_FIXTURE)
    assert p.digest((fixture / "manifest.json").read_bytes()) == R2_MANIFEST_SHA
    assert p.digest((fixture / "dates-index.json").read_bytes()) == R2_INDEX_SHA
    out.mkdir()
    names = ["manifest.json", "dates-index.json"]
    m = json.loads((fixture / "manifest.json").read_bytes())
    names += [f["name"] for f in m["files"].values()]
    for name in names:
        (out / name).write_bytes((fixture / name).read_bytes())
    return out


def acceptance(directory):
    raw = (directory / "manifest.json").read_bytes()
    return p.Acceptance(p.digest(raw), p.digest((directory / "dates-index.json").read_bytes()),
                        json.loads(raw)["source_observation"])


class MemoryStore(p.ObservedBackend):
    repo = p.REPO

    def __init__(self):
        self.data, self.events = {}, []
        self.fail_at = None
        self.after_archive = None

    def validate_candidate(self, manifest):
        assert manifest["tag"] == p.edition(DAY, 2)
        assert manifest["consumer_contract"] == p.CHANNEL
        assert manifest["repo"] == self.repo

    def read(self, tag, name, limit=p.MAX_FILE, *, require_encrypted=False):
        assert require_encrypted, "all publication reads must require encryption"
        return self.data.get((tag, name))

    def ensure_release(self, tag):
        assert tag.startswith(p.PREFIX)
        self.events.append(("reserve", tag))

    def archive(self, tag, paths):
        for path in paths:
            if self.fail_at == path.name:
                raise p.RevisionError("injected upload interruption")
            raw = path.read_bytes()
            key = tag, path.name
            if key in self.data and self.data[key] != raw:
                raise p.RevisionError("collision")
            self.data[key] = raw
            self.events.append(("asset", path.name))
        if self.after_archive:
            self.after_archive(self)

    def replace_index(self, tag, path, expected):
        assert tag == p.INDEX_TAG
        if self.data.get((tag, "dates-index.json")) != expected:
            raise p.RevisionError("stale predecessor")
        self.data[tag, path.name] = path.read_bytes()
        self.events.append(("index", path.name))

    def restore_missing_index(self, tag, path):
        assert (tag, path.name) not in self.data
        self.data[tag, path.name] = path.read_bytes()
        self.events.append(("restore", path.name))


def publish(candidate, tmp_path, store, accepted=None):
    return p.publish_candidate(candidate, tmp_path / "state", accepted or acceptance(candidate),
                               production_lock_path=tmp_path / "production.lock", store=store)


@pytest.fixture(autouse=True)
def portable_protocol_state_directory(request, monkeypatch):
    """Windows protocol tests do not pretend mode bits establish Windows ACLs.

    Real permission controls below retain the production helper; Linux executes
    the entire suite against its real permission checks without this substitution.
    """
    if os.name == "posix" or request.node.name.startswith("test_private_directory"):
        return
    def task_owned_protocol_directory(path):
        assert path.absolute() == path.resolve()
        path.mkdir(mode=0o700, exist_ok=True)
    monkeypatch.setattr(p, "private_directory", task_owned_protocol_directory)


def test_accepted_assets_first_index_last_and_retry(candidate, tmp_path):
    store = MemoryStore()
    receipt = publish(candidate, tmp_path, store)
    assert receipt["manifest_sha256"] == acceptance(candidate).manifest_sha256
    accepted_source = json.loads((candidate / "manifest.json").read_bytes())["source_observation"]
    assert receipt["source_observation"] == accepted_source
    assert receipt["source_observation"]["observation_state"] == "partial"
    assert not receipt["legacy_selected"] and not receipt["hosted_isolation_verified"]
    events = [x for x in store.events if x[0] != "reserve"]
    assert [x[0] for x in events] == ["asset"] * 3 + ["index"]
    assert events[-2] == ("asset", "manifest.json")
    before = copy.deepcopy(store.data)
    assert publish(candidate, tmp_path, store) == receipt
    assert store.data == before
    assert all(k[0].startswith(p.PREFIX) for k in store.data)


def tree_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


@pytest.mark.parametrize("placement", [
    "same-state", "state-inside-candidate", "candidate-inside-state",
    "lock-inside-candidate", "lock-is-candidate-file", "lock-is-candidate",
    "lock-ancestor", "lock-inside-state", "lock-is-state", "state-inside-lock",
    "state-is-recovery-lock", "state-inside-recovery-lock", "dotdot-alias",
])
def test_overlapping_publication_paths_refused_before_any_write(candidate, tmp_path, placement):
    state, lock = tmp_path / "state", tmp_path / "production.lock"
    if placement == "same-state": state = candidate
    if placement == "state-inside-candidate": state = candidate / "new" / "state"
    if placement == "candidate-inside-state": state = tmp_path
    if placement == "lock-inside-candidate": lock = candidate / "new" / "production.lock"
    if placement == "lock-is-candidate-file": lock = candidate / "manifest.json"
    if placement == "lock-is-candidate": lock = candidate
    if placement == "lock-ancestor": lock = tmp_path
    if placement == "lock-inside-state": lock = state / "production.lock"
    if placement == "lock-is-state": lock = state
    if placement == "state-inside-lock": state = lock / "state"
    if placement == "state-is-recovery-lock": state = p.recovery_lock_path(lock)
    if placement == "state-inside-recovery-lock": state = p.recovery_lock_path(lock) / "state"
    if placement == "dotdot-alias": state = candidate / ".." / candidate.name
    approved, before, store = acceptance(candidate), tree_bytes(tmp_path), MemoryStore()
    with patch.object(p, "production_lock", side_effect=AssertionError("unexpected lock write")), \
            patch.object(p, "private_directory", side_effect=AssertionError("unexpected state write")), \
            patch.object(store, "read", side_effect=AssertionError("unexpected remote read")):
        with pytest.raises(p.RevisionError, match="disjoint|canonical"):
            p.publish_candidate(candidate, state, approved, production_lock_path=lock, store=store)
    assert tree_bytes(tmp_path) == before
    assert not store.events and not store.data


@pytest.mark.skipif(os.name != "posix", reason="real links require POSIX test filesystem")
@pytest.mark.parametrize("alias", ["candidate", "state", "lock-parent", "recovery", "hardlink"])
def test_publication_link_alias_refused_before_lock_or_staging(candidate, tmp_path, alias):
    directory, state, lock = candidate, tmp_path / "state", tmp_path / "production.lock"
    link = tmp_path / "alias"
    if alias == "candidate":
        link.symlink_to(candidate, target_is_directory=True)
        directory = link
    if alias == "state":
        link.symlink_to(candidate, target_is_directory=True)
        state = link / "new-state"
    if alias == "lock-parent":
        link.symlink_to(candidate, target_is_directory=True)
        lock = link / "new.lock"
    if alias == "recovery":
        p.recovery_lock_path(lock).symlink_to(candidate / "manifest.json")
    if alias == "hardlink": os.link(candidate / "manifest.json", lock)
    before, store = tree_bytes(tmp_path), MemoryStore()
    with patch.object(p, "production_lock", side_effect=AssertionError("unexpected lock write")):
        with pytest.raises(p.RevisionError, match="canonical|link|control inode"):
            p.publish_candidate(directory, state, acceptance(candidate), production_lock_path=lock, store=store)
    assert tree_bytes(tmp_path) == before and not store.events


def test_disjoint_sibling_prefix_paths_remain_supported(candidate, tmp_path):
    # String-prefix comparison would wrongly reject these separate paths.
    state, lock = tmp_path / "candidate-state", tmp_path / "candidate.lock"
    before = tree_bytes(candidate)
    receipt = p.publish_candidate(candidate, state, acceptance(candidate),
                                  production_lock_path=lock, store=MemoryStore())
    assert receipt["manifest_sha256"] == acceptance(candidate).manifest_sha256
    assert tree_bytes(candidate) == before


@pytest.mark.parametrize("target", ["core", "details", "manifest"])
def test_interruption_preserves_index_then_resumes(candidate, tmp_path, target):
    store = MemoryStore()
    m = json.loads((candidate / "manifest.json").read_bytes())
    store.fail_at = "manifest.json" if target == "manifest" else m["files"][target]["name"]
    with pytest.raises(p.RevisionError):
        publish(candidate, tmp_path, store)
    assert (p.INDEX_TAG, "dates-index.json") not in store.data
    store.fail_at = None
    publish(candidate, tmp_path, store)
    assert (p.INDEX_TAG, "dates-index.json") in store.data


@pytest.mark.parametrize("file", ["manifest.json", "dates-index.json", "core", "details"])
def test_mutated_accepted_input_never_writes_remote(candidate, tmp_path, file):
    approved = acceptance(candidate)
    if file in {"core", "details"}:
        file = json.loads((candidate / "manifest.json").read_bytes())["files"][file]["name"]
    with (candidate / file).open("ab") as f:
        f.write(b" ")
    store = MemoryStore()
    with pytest.raises(p.RevisionError):
        publish(candidate, tmp_path, store, approved)
    assert not store.events


def test_immutable_remote_collision(candidate, tmp_path):
    store = MemoryStore()
    m = json.loads((candidate / "manifest.json").read_bytes())
    store.data[m["tag"], "manifest.json"] = b"other"
    with pytest.raises(p.RevisionError):
        publish(candidate, tmp_path, store)
    assert (p.INDEX_TAG, "dates-index.json") not in store.data


def prior_index(candidate):
    ix = json.loads((candidate / "dates-index.json").read_bytes())
    head = ix["revision_heads"][DAY]
    head["revision"] = 1
    head["manifest_url"] = p.url(p.edition(DAY, 1), "manifest.json")
    head["manifest_sha256"] = "a" * 64
    return p.canonical(ix)


def test_crash_missing_index_recovers_predecessor_before_commit(candidate, tmp_path):
    store = MemoryStore()
    old = prior_index(candidate)
    store.data[p.INDEX_TAG, "dates-index.json"] = old
    store.fail_at = "manifest.json"
    with pytest.raises(p.RevisionError):
        publish(candidate, tmp_path, store)
    del store.data[p.INDEX_TAG, "dates-index.json"]
    store.fail_at = None
    publish(candidate, tmp_path, store)
    assert ("restore", "dates-index.json") in store.events


def test_concurrent_index_change_is_not_overwritten(candidate, tmp_path):
    store = MemoryStore()
    changed = prior_index(candidate)
    store.after_archive = lambda s: s.data.update({(p.INDEX_TAG, "dates-index.json"): changed})
    with pytest.raises(p.RevisionError, match="changed during"):
        publish(candidate, tmp_path, store)
    assert store.data[p.INDEX_TAG, "dates-index.json"] == changed
    store.after_archive = None
    with pytest.raises(p.RevisionError, match="changed since"):
        publish(candidate, tmp_path, store)


def test_readback_corruption_does_not_select(candidate, tmp_path):
    store = MemoryStore()
    m = json.loads((candidate / "manifest.json").read_bytes())
    store.after_archive = lambda s: s.data.update({(m["tag"], "manifest.json"): b"wrong"})
    with pytest.raises(p.RevisionError, match="readback"):
        publish(candidate, tmp_path, store)
    assert (p.INDEX_TAG, "dates-index.json") not in store.data


@pytest.mark.parametrize("change", ["legacy-tag", "legacy-url", "unknown-capability", "wrong-date", "extra-asset", "source-date"])
def test_contract_mismatch_even_if_caller_hashes_new_bytes(candidate, tmp_path, change):
    path = candidate / "manifest.json"
    m = json.loads(path.read_bytes())
    if change == "legacy-tag": m["tag"] = "app-payload-latest"
    if change == "legacy-url": m["files"]["core"]["url"] = p.url("app-payload-latest", m["files"]["core"]["name"])
    if change == "unknown-capability": m["consumer_contract"] = "observed-population-v2"
    if change == "wrong-date": m["run_date"] = PREVIOUS_DAY
    if change == "extra-asset": m["public_rate_catalogue"] = None
    if change == "source-date": m["source_observation"]["observation_date"] = PREVIOUS_DAY
    path.write_bytes(p.canonical(m))
    store = MemoryStore()
    with pytest.raises(p.RevisionError): publish(candidate, tmp_path, store)
    assert not store.events


def test_index_preserves_other_dates_and_refuses_rollback(candidate):
    m, ix, _ = p.load_candidate(candidate, acceptance(candidate))
    old = json.loads(prior_index(candidate))
    h = copy.deepcopy(old["revision_heads"][DAY])
    h["manifest_url"] = p.url(p.edition(PREVIOUS_DAY, 1), "manifest.json")
    old["revision_heads"][PREVIOUS_DAY] = h
    old.update(dates=[PREVIOUS_DAY, DAY], count=2, min_date=PREVIOUS_DAY)
    out = json.loads(p.advance_index(p.canonical(old), ix, m))
    assert out["revision_heads"][PREVIOUS_DAY] == h
    old["revision_heads"][DAY]["revision"] = 3
    old["revision_heads"][DAY]["manifest_url"] = p.url(p.edition(DAY, 3), "manifest.json")
    with pytest.raises(p.RevisionError): p.advance_index(p.canonical(old), ix, m)


@pytest.mark.parametrize("mode,links", [(stat.S_IFREG, 2), (stat.S_IFLNK, 1), (stat.S_IFDIR, 1)])
def test_unsafe_inode_refused_before_open(mode, links):
    # Windows sandbox denies link creation; test the admission predicate directly.
    path = SimpleNamespace(lstat=lambda: SimpleNamespace(st_mode=mode, st_nlink=links, st_size=1))
    with pytest.raises(p.RevisionError, match="unsafe"):
        p.bounded_file(path)


def test_secure_upload_uses_are2_and_exact_bytes_without_real_credentials(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_bytes(b'{"test":true}')
    key = b"\x19" * 32
    seen = []
    def runner(args, **kwargs):
        wire = Path(args[4]).read_bytes()
        assert wire.startswith(MAGIC) and wire != path.read_bytes()
        assert decrypt_transport(wire, lambda _: key) == path.read_bytes()
        seen.append(args)
        return subprocess.CompletedProcess(args, 0)
    with patch("app_payload_secure_upload.publication_key", return_value=key), patch("tempfile.tempdir", str(tmp_path)):
        secure_upload(["gh", "release", "upload", p.INDEX_TAG, str(path), "--repo", p.REPO], runner=runner)
    assert len(seen) == 1


@pytest.mark.parametrize("bad", [None, "body", "prerelease", "draft", "asset"])
def test_real_store_reservation_identity_and_prerelease_flags(candidate, bad):
    m = json.loads((candidate / "manifest.json").read_bytes())
    store = p.ObservedStore(m, gh="never-executed")
    meta = dict(tag_name=m["tag"], body=store.reservations[m["tag"]], prerelease=True, draft=False, assets=[])
    if bad == "body": meta["body"] = "unrelated"
    if bad == "prerelease": meta["prerelease"] = False
    if bad == "draft": meta["draft"] = True
    if bad == "asset": meta["assets"] = [{"name": "unapproved.json"}]
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1: return subprocess.CompletedProcess(args, 1, "", "HTTP 404")
        return subprocess.CompletedProcess(args, 0, json.dumps(meta), "")
    with patch.object(store, "_run", side_effect=run), patch.object(p, "publication_key", return_value=b"x" * 32):
        if bad:
            with pytest.raises(p.RevisionError): store.ensure_release(m["tag"])
        else: store.ensure_release(m["tag"])
    assert "--prerelease" in calls[1] and "--latest=false" in calls[1]


def test_store_refuses_legacy_mutations(candidate, tmp_path):
    m = json.loads((candidate / "manifest.json").read_bytes())
    store = p.ObservedStore(m, gh="never-executed")
    with pytest.raises(p.RevisionError): store.ensure_release("app-payload-latest")
    with pytest.raises(p.RevisionError): store.archive("app-payload-latest", [])
    with pytest.raises(p.RevisionError): store.replace_index("app-payload-latest", tmp_path / "dates-index.json", None)
    with pytest.raises(p.RevisionError): store.restore_missing_index("app-payload-latest", tmp_path / "dates-index.json")


@pytest.mark.parametrize("uncertain_manifest_upload", [False, True])
def test_real_backend_are2_transaction_no_network(candidate, tmp_path, uncertain_manifest_upload):
    """Real secure_upload, archive, index replace and authenticated decode; fake wire/CLI only."""
    m = json.loads((candidate / "manifest.json").read_bytes())
    store = p.ObservedStore(m, gh="never-executed")
    key, releases, wire, uploads = b"\x27" * 32, {}, {}, []
    def cli(args, **kwargs):
        if args[1] == "api":
            tag = args[2].split("/tags/")[1]
            if tag not in releases:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 404")
            return subprocess.CompletedProcess(args, 0, json.dumps(releases[tag]), "")
        assert args[1] == "release"
        tag = args[3]
        assert tag in {m["tag"], p.INDEX_TAG}
        if args[2] == "create":
            assert "--prerelease" in args and "--latest=false" in args
            releases[tag] = dict(tag_name=tag, body=args[args.index("--notes") + 1],
                                 prerelease=True, draft=False, assets=[])
        else:
            assert args[2] == "upload"
            path = Path(args[4])
            raw = path.read_bytes()
            assert raw.startswith(MAGIC)
            assert tag == p.INDEX_TAG if "--clobber" in args else tag == m["tag"]
            wire[tag, path.name] = raw
            releases[tag]["assets"].append({"name": path.name})
            uploads.append((tag, path.name))
            if uncertain_manifest_upload and path.name == "manifest.json":
                return subprocess.CompletedProcess(args, 1, "", "injected ambiguous upload error")
        return subprocess.CompletedProcess(args, 0, "", "")
    def read_wire(asset_url, limit=p.MAX_FILE):
        tag, name = asset_url.rsplit("/", 2)[-2:]
        return wire.get((tag, name))
    with patch("subprocess.run", side_effect=cli), patch.object(store, "read_wire_url", side_effect=read_wire), \
            patch.object(p, "publication_key", return_value=key), \
            patch("app_payload_secure_upload.publication_key", return_value=key), \
            patch("app_payload_revisions_github.publication_key", return_value=key), \
            patch("tempfile.tempdir", str(tmp_path)):
        receipt = publish(candidate, tmp_path, store)
    assert uploads[-1] == (p.INDEX_TAG, "dates-index.json")
    assert len(uploads) == 4 and receipt["manifest_sha256"] == acceptance(candidate).manifest_sha256
    assert decrypt_transport(wire[m["tag"], "manifest.json"], lambda _: key) == (candidate / "manifest.json").read_bytes()


def test_same_api_ctime_mutation_is_rejected(candidate):
    path = candidate / "manifest.json"
    original = os.fstat
    calls = 0
    def changed(fd):
        nonlocal calls
        calls += 1
        s = original(fd)
        values = {k: getattr(s, k) for k in ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")}
        if calls == 2:
            values["st_ctime_ns"] += 1
        return SimpleNamespace(**values)
    with patch.object(p.os, "fstat", side_effect=changed), pytest.raises(p.RevisionError, match="changed during"):
        p.bounded_file(path)


def test_final_index_growth_refused_before_reservation_or_egress(candidate, tmp_path):
    m, ix, _ = p.load_candidate(candidate, acceptance(candidate))
    head = ix["revision_heads"][m["run_date"]]
    def index_with(count):
        days = [(date(2000, 1, 1) + timedelta(days=i)).isoformat() for i in range(count)]
        heads = {d: {**head, "manifest_url": p.url(p.edition(d, 2), "manifest.json")} for d in days}
        return p.canonical({**ix, "dates": days, "count": count, "min_date": days[0],
                            "latest_date": days[-1], "revision_heads": heads})
    low, high = 1, 4000
    assert len(index_with(high)) > 1024 * 1024
    while low + 1 < high:
        mid = (low + high) // 2
        if len(index_with(mid)) <= 1024 * 1024: low = mid
        else: high = mid
    before = index_with(low)
    p.validate_index(before)  # Genuine valid predecessor, not malformed test data.
    store = MemoryStore()
    store.data[p.INDEX_TAG, "dates-index.json"] = before
    with pytest.raises(p.RevisionError, match="consumer budget"):
        publish(candidate, tmp_path, store)
    assert not store.events
    assert store.data[p.INDEX_TAG, "dates-index.json"] == before
    assert not (tmp_path / "state" / m["tag"] / "transaction.json").exists()


@pytest.mark.parametrize("explicit_false", [False, True])
def test_observed_read_never_accepts_plaintext(candidate, explicit_false):
    m = json.loads((candidate / "manifest.json").read_bytes())
    store = p.ObservedStore(m, gh="never-executed")
    with patch.object(store, "read_wire_url", return_value=(candidate / "dates-index.json").read_bytes()):
        with pytest.raises(PlaintextTransportError):
            if explicit_false:
                store.read(p.INDEX_TAG, "dates-index.json", require_encrypted=False)
            else:
                store.read(p.INDEX_TAG, "dates-index.json")


def test_plaintext_predecessor_refused_before_any_reservation(candidate, tmp_path):
    m = json.loads((candidate / "manifest.json").read_bytes())
    store = p.ObservedStore(m, gh="never-executed")
    with patch.object(store, "read_wire_url", return_value=prior_index(candidate)), \
            patch.object(store, "_run", side_effect=AssertionError("unexpected GitHub mutation")):
        with pytest.raises(PlaintextTransportError):
            publish(candidate, tmp_path, store)
    assert not (tmp_path / "state" / m["tag"] / "transaction.json").exists()


def test_inherited_commit_predecessor_recheck_rejects_plaintext(candidate, tmp_path):
    m = json.loads((candidate / "manifest.json").read_bytes())
    store = p.ObservedStore(m, gh="never-executed")
    before = prior_index(candidate)
    with patch.object(store, "ensure_release") as reserve, \
            patch.object(store, "read_wire_url", return_value=before), \
            patch.object(store, "_run", side_effect=AssertionError("unexpected index upload")):
        with pytest.raises(PlaintextTransportError):
            store.replace_index(p.INDEX_TAG, candidate / "dates-index.json", before)
    reserve.assert_called_once_with(p.INDEX_TAG)


@pytest.mark.parametrize("kind", ["generic", "duck_typed"])
def test_uncontracted_backend_refused_before_lock_or_staging(candidate, tmp_path, kind):
    if kind == "generic":
        store = p.GitHubRevisionStore(p.REPO, gh="never-executed")
    else:
        explicit = MemoryStore()
        store = SimpleNamespace(repo=p.REPO, **{name: getattr(explicit, name) for name in (
            "read", "ensure_release", "archive", "replace_index", "restore_missing_index", "validate_candidate")})
    with patch.object(p, "production_lock", side_effect=AssertionError("unexpected lock acquisition")):
        with pytest.raises(p.RevisionError, match="explicit isolated"):
            publish(candidate, tmp_path, store)
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("difference", ["candidate", "reservation", "asset_allowlist"])
def test_real_backend_exact_reservation_required_before_staging(candidate, tmp_path, difference):
    m = json.loads((candidate / "manifest.json").read_bytes())
    configured = copy.deepcopy(m)
    if difference == "candidate":
        configured["generated_at"] = "2026-05-19T05:00:00Z"
    store = p.ObservedStore(configured, gh="never-executed")
    if difference == "reservation": store.reservations[p.INDEX_TAG] = "other"
    if difference == "asset_allowlist": store.names[m["tag"]].add("unaccepted.json")
    with patch.object(store, "_run", side_effect=AssertionError("unexpected egress")):
        with pytest.raises(p.RevisionError, match="reservation differs"):
            publish(candidate, tmp_path, store)
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize("mode,uid", [
    (stat.S_IFDIR | 0o755, 1000), (stat.S_IFDIR | 0o750, 1000),
    (stat.S_IFDIR | 0o770, 1000), (stat.S_IFDIR | 0o1700, 1000),
    (stat.S_IFDIR | 0o700, 1001), (stat.S_IFREG | 0o700, 1000),
])
def test_private_directory_mode_or_owner_refusal(mode, uid):
    with pytest.raises(p.RevisionError, match="current-owner mode 0700"):
        p.require_private_mode(SimpleNamespace(st_mode=mode, st_uid=uid), 1000)


def test_private_directory_mode_and_owner_accepted():
    p.require_private_mode(SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1000), 1000)


@pytest.mark.skipif(os.name != "posix", reason="real POSIX mode/owner evidence requires POSIX")
def test_private_directory_created_and_existing_private_unchanged(tmp_path):
    path = tmp_path / "state"
    p.private_directory(path)
    before = path.stat()
    assert stat.S_IMODE(before.st_mode) == 0o700 and before.st_uid == os.geteuid()
    p.private_directory(path)
    after = path.stat()
    assert (before.st_mode, before.st_uid, before.st_ino) == (after.st_mode, after.st_uid, after.st_ino)


@pytest.mark.skipif(os.name != "posix", reason="real POSIX mode/owner evidence requires POSIX")
def test_private_directory_existing_exposure_refused_without_permission_rewrite(candidate, tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    state.chmod(0o755)  # Deliberately construct this test's exposed pre-existing state.
    before = state.stat()
    store = MemoryStore()
    with pytest.raises(p.RevisionError, match="current-owner mode 0700"):
        publish(candidate, tmp_path, store)
    after = state.stat()
    assert (before.st_mode, before.st_uid, before.st_ctime_ns) == (after.st_mode, after.st_uid, after.st_ctime_ns)
    assert not list(state.iterdir()) and not store.events


@pytest.mark.skipif(os.name != "posix", reason="real POSIX directory creation requires POSIX")
def test_private_directory_does_not_create_default_mode_intermediate_parents(tmp_path):
    with pytest.raises(FileNotFoundError):
        p.private_directory(tmp_path / "missing" / "state")
    assert not (tmp_path / "missing").exists()


@pytest.mark.skipif(os.name == "posix", reason="non-POSIX publication refusal only")
def test_private_directory_non_posix_refused_without_false_acl_claim(tmp_path):
    with pytest.raises(p.RevisionError, match="requires POSIX permission validation"):
        p.private_directory(tmp_path / "state")
    assert not (tmp_path / "state").exists()


def test_missing_index_with_published_history_fails_closed(candidate, tmp_path):
    """A missing remote index after earlier editions must not restart the channel."""
    store = MemoryStore()
    earlier = tmp_path / "state" / p.edition(PREVIOUS_DAY, 1)
    earlier.mkdir(parents=True, mode=0o700)
    (tmp_path / "state").chmod(0o700)
    (earlier / "receipt.json").write_text("{}")
    with pytest.raises(p.RevisionError, match="earlier editions were published"):
        publish(candidate, tmp_path, store)
    assert not [x for x in store.events if x[0] in ("asset", "index")]


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission control")
def test_restore_staging_directory_is_private_before_index_replacement(candidate, tmp_path):
    store = MemoryStore()
    store.data[p.INDEX_TAG, "dates-index.json"] = prior_index(candidate)
    seen = []
    original = store.replace_index
    def check_private(tag, path, expected):
        restore = path.parent / "restore"
        seen.append(oct(restore.lstat().st_mode & 0o777))
        return original(tag, path, expected)
    store.replace_index = check_private
    old = os.umask(0o022)
    try:
        publish(candidate, tmp_path, store)
    finally:
        os.umask(old)
    assert seen == ["0o700"]
