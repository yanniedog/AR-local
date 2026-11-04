"""Prepared observed-channel transaction; no CLI or implicit network execution.

Admission, source-closure/consumer acceptance, service isolation and window/resource
checks belong to the coordinator. Acceptance binds those reviewed bytes, not a
claim that this module independently validated source membership or native UI.
The caller uses the existing service credentials and global production lock.
"""
from __future__ import annotations

import os
import re
import stat
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from app_payload_revisions_github import GitHubRevisionStore, write_once
from app_payload_revisions_state import (
    RevisionError, bundle_sha256, canonical, decode_document, digest, validate_date,
    validate_manifest,
)
from app_payload_secure_upload import publication_key
from ar_local_operation_lock import production_lock, recovery_lock_path

REPO = "yanniedog/AR-local"
CHANNEL = "observed-population-v1"
INDEX_TAG = "app-payload-observed-v1-candidate"
PREFIX = "app-payload-observed-v1-"
MAX_FILE = 8 * 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}")
HEAD_KEYS = {"revision", "generation_id", "manifest_url", "manifest_sha256", "bundle_sha256"}


def url(tag, name):
    return f"https://github.com/{REPO}/releases/download/{tag}/{name}"


def edition(day, revision):
    validate_date(day)
    if type(revision) is not int or not 1 <= revision <= 999999:
        raise RevisionError("unsupported observed revision")
    return f"{PREFIX}{day}-r{revision:06d}"


def bounded_file(path):
    """Reject links and mutations; cross-API identity excludes Windows ctime only."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > MAX_FILE:
        raise RevisionError("unsafe candidate file")
    identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_nlink, s.st_size, s.st_mtime_ns)
    stable = lambda s: (*identity(s), s.st_ctime_ns)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if identity(before) != identity(opened):
            raise RevisionError("candidate replaced before read")
        raw = stream.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE or stable(opened) != stable(os.fstat(stream.fileno())):
            raise RevisionError("candidate changed during read")
    if stable(before) != stable(path.lstat()) or len(raw) != before.st_size:
        raise RevisionError("candidate changed after read")
    return raw


def require_private_mode(info, owner_uid):
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != owner_uid
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise RevisionError("publication state requires current-owner mode 0700")


def private_directory(path):
    if os.name != "posix":
        raise RevisionError("private publication state requires POSIX permission validation")
    if path.absolute() != path.resolve():
        raise RevisionError("publication state directory follows a link")
    # Parent must already exist. parents=True would create intermediate directories
    # using default permissions; never broaden or rewrite existing permissions.
    path.mkdir(mode=0o700, exist_ok=True)
    require_private_mode(path.lstat(), os.geteuid())
    if path.absolute() != path.resolve():
        raise RevisionError("unsafe publication state directory")


def publication_paths(directory, state, lock):
    """Reject overlapping coordinator paths before any lock or state writes."""
    paths = [Path(value).absolute() for value in (directory, state, lock)]
    # Resolve aliases before containment checks, but do not follow links during
    # publication. Trusted coordinator parents must remain stable throughout.
    resolved = [path.resolve() for path in paths]
    if paths != resolved:
        raise RevisionError("publication paths must be canonical and not follow links")
    directory, state, lock = resolved
    controls = (lock, recovery_lock_path(lock))
    roots = (directory, state)
    overlaps = lambda a, b: a == b or a in b.parents or b in a.parents
    if overlaps(directory, state) or any(overlaps(root, control) for root in roots for control in controls):
        raise RevisionError("candidate, state and publication lock paths must be disjoint")
    for control in controls:
        if control.resolve() != control:
            raise RevisionError("publication control path follows a link")
        if control.exists():
            info = control.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RevisionError("unsafe publication control inode")
    return directory, state, lock


def validate_index(raw):
    if len(raw) > 1024 * 1024:
        raise RevisionError("candidate index exceeds consumer budget")
    ix = decode_document(raw)
    if (set(ix) != {"schema_version", "revision_protocol", "channel", "dates", "count",
                    "min_date", "latest_date", "revision_heads"}
            or type(ix["schema_version"]) is not int or ix["schema_version"] != 1
            or type(ix["revision_protocol"]) is not int or ix["revision_protocol"] != 1
            or ix["channel"] != CHANNEL or not isinstance(ix["dates"], list)
            or not ix["dates"] or not all(isinstance(d, str) for d in ix["dates"])
            or ix["dates"] != sorted(set(ix["dates"]))
            or type(ix["count"]) is not int or ix["count"] != len(ix["dates"])
            or ix["min_date"] != ix["dates"][0] or ix["latest_date"] != ix["dates"][-1]
            or not isinstance(ix["revision_heads"], dict)
            or set(ix["revision_heads"]) != set(ix["dates"])):
        raise RevisionError("invalid isolated index")
    for day, h in ix["revision_heads"].items():
        if not isinstance(h, dict) or set(h) != HEAD_KEYS:
            raise RevisionError("invalid isolated head")
        tag = edition(day, h["revision"])
        if (not HASH.fullmatch(str(h["bundle_sha256"]))
                or not HASH.fullmatch(str(h["manifest_sha256"]))
                or h["generation_id"] != "sha256-" + h["bundle_sha256"]
                or h["manifest_url"] != url(tag, "manifest.json")):
            raise RevisionError("head escaped observed namespace")
    return ix


@dataclass(frozen=True)
class Acceptance:
    """Exact bytes previously accepted by independent source and consumer checks."""
    manifest_sha256: str
    index_sha256: str
    source_observation: dict


def load_candidate(directory, accepted):
    raw = bounded_file(directory / "manifest.json")
    ix_raw = bounded_file(directory / "dates-index.json")
    if digest(raw) != accepted.manifest_sha256 or digest(ix_raw) != accepted.index_sha256:
        raise RevisionError("candidate differs from accepted immutable bytes")
    m, ix = decode_document(raw), validate_index(ix_raw)
    if len(raw) > 4 * 1024 * 1024 or canonical(m) != raw:
        raise RevisionError("accepted manifest must retain canonical producer bytes")
    validate_manifest(m)
    allowed = {"schema_version", "consumer_contract", "counts", "files", "generated_at",
               "payload_revision", "repo", "run_date", "schedule", "source_observation",
               "tag", "app_min_version"}
    if (set(m) != allowed or m["consumer_contract"] != CHANNEL or m["repo"] != REPO
            or set(m["files"]) != {"core", "details"}
            or m["source_observation"] != accepted.source_observation
            or m["source_observation"].get("observation_date") != m["run_date"]
            or m["source_observation"].get("observation_state") != "partial"):
        raise RevisionError("unsupported observed edition or source binding")
    r = m["payload_revision"]
    if (set(r) != {"schema_version", "revision", "parent_revision", "bundle_sha256", "generation_id"}
            or type(r["schema_version"]) is not int or r["schema_version"] != 1
            or type(r["parent_revision"]) is not int or not 0 <= r["parent_revision"] < r["revision"]):
        raise RevisionError("invalid revision ancestry")
    tag = edition(m["run_date"], r["revision"])
    bundle = bundle_sha256(m)
    h = dict(revision=r["revision"], bundle_sha256=bundle, generation_id="sha256-" + bundle,
             manifest_sha256=digest(raw), manifest_url=url(tag, "manifest.json"))
    if (m["tag"] != tag or r["bundle_sha256"] != bundle or r["generation_id"] != h["generation_id"]
            or ix["dates"] != [m["run_date"]] or ix["revision_heads"][m["run_date"]] != h):
        raise RevisionError("candidate identity does not reconcile")
    files = {}
    for kind, f in m["files"].items():
        if (f["url"] != url(tag, f["name"])
                or f["name"] != f"{kind}-{m['run_date']}-{f['sha256'][:12]}.json.gz"):
            raise RevisionError("asset escaped observed namespace")
        data = bounded_file(directory / f["name"])
        if len(data) != f["bytes"] or digest(data) != f["sha256"]:
            raise RevisionError("candidate asset differs from accepted manifest")
        files[f["name"]] = data
    files["manifest.json"] = raw
    return m, ix, files


def advance_index(before, candidate, manifest):
    if before is None:
        output = canonical(candidate)
        validate_index(output)
        return output
    current = validate_index(before)
    day = manifest["run_date"]
    head = candidate["revision_heads"][day]
    old = current["revision_heads"].get(day)
    if old:
        if old == head:
            return before
        if (head["revision"] <= old["revision"]
                or manifest["payload_revision"]["parent_revision"] != old["revision"]):
            raise RevisionError("revision rollback, collision or changed predecessor")
    heads = {**current["revision_heads"], day: head}
    dates = sorted(heads)
    output = canonical({**current, "revision_heads": heads, "dates": dates, "count": len(dates),
                        "min_date": dates[0], "latest_date": dates[-1]})
    validate_index(output)
    return output


class ObservedBackend(ABC):
    """Explicit isolated backend contract, including deliberately declared doubles.

    Implementations must preserve observed prerelease reservations, encrypted reads,
    immutable uploads and predecessor-checked index commits. Generic legacy stores
    do not implement this contract. Acceptance of arbitrary duck-typed I/O is unsafe.
    """
    @abstractmethod
    def validate_candidate(self, manifest):
        """Reject unless configured for this exact accepted reservation."""

    @abstractmethod
    def read(self, tag, name, limit=MAX_FILE, *, require_encrypted=True):
        """Read only isolated assets, requiring authenticated ARE2."""

    @abstractmethod
    def ensure_release(self, tag):
        """Reserve or verify the exact isolated prerelease metadata."""

    @abstractmethod
    def archive(self, tag, paths):
        """Upload immutable encrypted assets with authenticated readback."""

    @abstractmethod
    def replace_index(self, tag, path, expected):
        """Replace the isolated index only after an exact predecessor check."""

    @abstractmethod
    def restore_missing_index(self, tag, path):
        """Restore the isolated predecessor only while absent."""


class ObservedStore(GitHubRevisionStore, ObservedBackend):
    """Restrict generic encrypted I/O to this transaction's two prereleases."""
    def __init__(self, manifest, gh=None):
        if (manifest.get("consumer_contract") != CHANNEL or manifest.get("repo") != REPO
                or manifest.get("tag") != edition(manifest["run_date"], manifest["payload_revision"]["revision"])):
            raise RevisionError("backend requires an isolated observed edition")
        super().__init__(REPO, gh)
        self.tag = manifest["tag"]
        self.reservations = {
            self.tag: canonical({"schema_version": 1, "channel": CHANNEL,
                                 "manifest_sha256": digest(canonical(manifest)),
                                 "source_observation": manifest["source_observation"]}).decode(),
            INDEX_TAG: canonical({"schema_version": 1, "channel": CHANNEL, "role": "index"}).decode(),
        }
        self.names = {self.tag: {"manifest.json", *(f["name"] for f in manifest["files"].values())},
                      INDEX_TAG: {"dates-index.json"}}

    def validate_candidate(self, manifest):
        expected = canonical({"schema_version": 1, "channel": CHANNEL,
                              "manifest_sha256": digest(canonical(manifest)),
                              "source_observation": manifest["source_observation"]}).decode()
        names = {"manifest.json", *(f["name"] for f in manifest["files"].values())}
        if (self.repo != REPO or self.tag != manifest["tag"]
                or self.reservations != {self.tag: expected, INDEX_TAG: canonical({
                    "schema_version": 1, "channel": CHANNEL, "role": "index"}).decode()}
                or self.names != {self.tag: names, INDEX_TAG: {"dates-index.json"}}):
            raise RevisionError("backend reservation differs from accepted candidate")

    def read(self, tag, name, limit=MAX_FILE, *, require_encrypted=True):
        # Generic legacy helpers permit plaintext predecessors. This channel never
        # does, including inherited replace/restore/uncertain-upload read paths.
        if tag not in self.names or name not in self.names[tag]:
            raise RevisionError("read outside reserved observed channel")
        return super().read(tag, name, limit, require_encrypted=True)

    def ensure_release(self, tag):
        if tag not in self.reservations:
            raise RevisionError("release outside reserved observed channel")
        publication_key()
        args = ["api", f"repos/{self.repo}/releases/tags/{tag}"]
        found = self._run(args, check=False)
        if found.returncode:
            if "HTTP 404" not in found.stderr:
                raise RevisionError("release lookup failed")
            # A create timeout/failure is uncertain; re-read the reserved identity.
            try:
                self._run(["release", "create", tag, "--repo", self.repo, "--title", tag,
                           "--notes", self.reservations[tag], "--prerelease", "--latest=false"])
            except Exception:
                found = self._run(args, check=False)
                if found.returncode:
                    raise RevisionError("release reservation unconfirmed") from None
            else:
                found = self._run(args, check=False)
        if found.returncode:
            raise RevisionError("release reservation unconfirmed")
        meta = decode_document(found.stdout.encode())
        if (meta.get("tag_name") != tag or meta.get("prerelease") is not True
                or meta.get("draft") is not False or meta.get("body") != self.reservations[tag]
                or not isinstance(meta.get("assets"), list)
                or any(a.get("name") not in self.names[tag] for a in meta["assets"])):
            raise RevisionError("occupied release differs from reservation")

    def archive(self, tag, paths):
        if tag != self.tag or any(p.name not in self.names[tag] for p in paths):
            raise RevisionError("immutable upload outside observed edition")
        return super().archive(tag, paths)

    def replace_index(self, tag, path, expected):
        if tag != INDEX_TAG or path.name != "dates-index.json":
            raise RevisionError("index replacement outside observed channel")
        self.ensure_release(tag)
        return super().replace_index(tag, path, expected)

    def restore_missing_index(self, tag, path):
        if tag != INDEX_TAG or path.name != "dates-index.json":
            raise RevisionError("restore outside observed channel")
        self.ensure_release(tag)
        return super().restore_missing_index(tag, path)


def publish_candidate(directory, state, accepted, *, production_lock_path, store):
    """No implicit backend: coordinator explicitly supplies the authorized context.

    Global lock covers reservation through final readback. A durable transaction
    permits only its exact predecessor/target on re-entry; never overwrite a
    changed head. State is private trusted coordinator storage, outside fixture.
    """
    if not isinstance(store, ObservedBackend):
        raise RevisionError("explicit isolated observed backend required")
    directory, state, production_lock_path = publication_paths(directory, state, production_lock_path)
    with production_lock(production_lock_path, "observed-population-publication"):
        manifest, index, files = load_candidate(directory, accepted)
        if store.repo != REPO:
            raise RevisionError("wrong publication repository")
        store.validate_candidate(manifest)
        tag = manifest["tag"]
        private_directory(state)
        transaction = state / tag
        private_directory(transaction)
        record = transaction / "transaction.json"
        current = store.read(INDEX_TAG, "dates-index.json", require_encrypted=True)
        if record.exists():
            saved = decode_document(bounded_file(record))
            before = bytes.fromhex(saved["predecessor_hex"]) if saved["predecessor_hex"] is not None else None
            after = bytes.fromhex(saved["target_hex"])
            if (saved["manifest_sha256"] != accepted.manifest_sha256
                    or after != advance_index(before, index, manifest)):
                raise RevisionError("reserved local transaction differs")
        else:
            if current is None and any((other / "receipt.json").exists()
                                       for other in state.iterdir() if other.name != tag):
                # Durable state shows earlier published editions; an empty-channel
                # index would drop them from discovery. Recover the index first.
                raise RevisionError("observed index missing although earlier editions were published")
            before, after = current, advance_index(current, index, manifest)
            write_once(record, canonical({"manifest_sha256": accepted.manifest_sha256,
                       "predecessor_hex": before.hex() if before is not None else None,
                       "target_hex": after.hex()}))
        if current not in (before, after) and not (current is None and before is not None):
            raise RevisionError("index changed since transaction reservation")
        # Private copies isolate upload reads from changes to the original fixture.
        for name, raw in files.items():
            write_once(transaction / name, raw)
            if bounded_file(transaction / name) != raw:
                raise RevisionError("staged candidate changed")
        index_path = transaction / "dates-index.json"
        write_once(index_path, after)
        store.ensure_release(tag)
        store.archive(tag, [transaction / n for n in files])  # manifest last
        for name, raw in files.items():
            if store.read(tag, name, max(len(raw), 1), require_encrypted=True) != raw:
                raise RevisionError("encrypted immutable readback failed")
        # Recheck predecessor AFTER all uploads, immediately before index commit.
        current = store.read(INDEX_TAG, "dates-index.json", require_encrypted=True)
        if current is None and before is not None:
            restore = transaction / "restore" / "dates-index.json"
            private_directory(restore.parent)
            write_once(restore, before)
            store.ensure_release(INDEX_TAG)
            store.restore_missing_index(INDEX_TAG, restore)
            current = before
        if current != after:
            if current != before:
                raise RevisionError("index changed during edition upload")
            # The inherited replacement stages its predecessor under restore/ via
            # write_once (default umask); create it private first so an
            # interrupted replacement can resume.
            private_directory(transaction / "restore")
            store.replace_index(INDEX_TAG, index_path, before)
        else:
            store.ensure_release(INDEX_TAG)
        if store.read(INDEX_TAG, "dates-index.json", require_encrypted=True) != after:
            raise RevisionError("encrypted isolated index readback failed")
        receipt = {"schema_version": 1, "channel": CHANNEL, "tag": tag,
                   "source_observation": manifest["source_observation"],
                   "manifest_sha256": accepted.manifest_sha256, "index_sha256": digest(after),
                   "legacy_selected": False, "hosted_isolation_verified": False,
                   "native_activation_verified": False}
        write_once(transaction / "receipt.json", canonical(receipt))
        return receipt
