"""Archive protocol tests use retained real CDR products/rates, not demo data."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app_payload_archive import archive_payload_bundle, build_and_archive_payload
from app_payload_revisions_state import RevisionError, canonical, digest
from tests.test_app_payload_revisions import DAY, REPO, MemoryStore, build_payload


class ArchiveStore(MemoryStore):
    def __init__(self):
        super().__init__()
        self.reads = []
        self.archived_paths = []

    def read(self, tag, name, limit=8 * 1024 * 1024, *, require_encrypted=False):
        assert require_encrypted, "Archive cannot accept legacy plaintext readback"
        assert tag.startswith("app-payload-archive-")
        self.reads.append((tag, name))
        return super().read(tag, name, limit)

    def archive(self, tag, paths):
        self.archived_paths.append([p.name for p in paths])
        super().archive(tag, paths)

    def tags(self):
        pytest.fail("Archive does not enumerate selected app revisions")

    def replace_index(self, *_):
        pytest.fail("Archive must never promote an index")

    def restore_missing_index(self, *_):
        pytest.fail("Archive must never restore an index")


def prepared(root):
    manifest = build_payload(root)
    # Protocol metadata only; product and rate bytes remain retained fixture data.
    manifest["source_observation"] = {
        "observation_date": DAY, "observation_state": "partial",
        "generation_id": "test-retained-fixture", "contract_digest": digest(canonical(manifest)),
    }
    manifest["schedule"] = {"next_due_utc": "2026-05-20T01:00:00Z"}
    (root / "manifest.json").write_bytes(canonical(manifest))
    return manifest


def archive(root, store, payload=None, state=None):
    return archive_payload_bundle(payload or root / "payload", state_dir=state or root / "state",
                                  contract_coverage={"failure_provenance_complete": False},
                                  promotion_reason="unverified_provider_population", repo=REPO, store=store)


def test_partial_archive_preserves_app_state_and_discloses_withheld_status(tmp_path):
    store = ArchiveStore()
    prepared(tmp_path / "payload")
    store.objects[("app-payload-latest", "manifest.json")] = b"previous selection"
    store.objects[("app-payload-latest", "dates-index.json")] = b"previous index"
    before = copy.deepcopy(store.objects)
    result = archive(tmp_path, store)
    assert result.tag.startswith(f"app-payload-archive-{DAY}-")
    assert result.manifest["retention"]["selected_for_app"] is False
    assert result.manifest["retention"]["observation_state"] == "partial"
    assert result.manifest["retention"]["promotion_reason"] == "unverified_provider_population"
    assert "schedule" not in result.manifest and "payload_revision" not in result.manifest
    assert store.archived_paths[-1][-1] == "manifest.json"
    assert set(before.items()) <= set(store.objects.items())
    assert store.promotions == 0
    assert result.manifest_sha256 == digest((result.archive_dir / "manifest.json").read_bytes())


def test_archive_retry_reuses_manifest_after_state_loss_and_rebuild(tmp_path):
    store = ArchiveStore()
    manifest = prepared(tmp_path / "payload")
    first = archive(tmp_path, store)
    before = copy.deepcopy(store.objects)
    manifest["generated_at"] = "2026-05-21T12:00:00Z"
    manifest["schedule"]["next_due_utc"] = "2026-05-22T01:00:00Z"
    (tmp_path / "payload/manifest.json").write_bytes(canonical(manifest))
    retry = archive(tmp_path, store, state=tmp_path / "new-state")
    assert retry.tag == first.tag
    assert retry.manifest == first.manifest and store.objects == before


def test_interrupted_upload_is_resumable_without_selection(tmp_path):
    store = ArchiveStore()
    prepared(tmp_path / "payload")
    store.fail_asset = "manifest.json"
    with pytest.raises(RevisionError, match="interrupted"):
        archive(tmp_path, store)
    retained = copy.deepcopy(store.objects)
    assert retained and all(name != "manifest.json" for _, name in retained)
    store.fail_asset = None
    result = archive(tmp_path, store)
    assert set(retained.items()) <= set(store.objects.items())
    assert (result.tag, "manifest.json") in store.objects


@pytest.mark.parametrize("fault", ["source", "date", "digest", "asset", "asset_date"])
def test_archive_refuses_invalid_source_or_bytes_before_egress(tmp_path, fault):
    store = ArchiveStore()
    manifest = prepared(tmp_path / "payload")
    if fault == "source":
        del manifest["source_observation"]
    elif fault == "date":
        manifest["source_observation"]["observation_date"] = "2026-05-18"
    elif fault == "digest":
        manifest["source_observation"]["contract_digest"] = "bad"
    elif fault == "asset":
        (tmp_path / "payload" / manifest["files"]["core"]["name"]).write_bytes(b"corrupt")
    else:
        manifest["run_date"] = "2026-05-18"
    (tmp_path / "payload/manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(RevisionError):
        archive(tmp_path, store)
    assert not store.objects and not store.reads


def test_archive_requires_independent_readback(tmp_path):
    class MissingReadback(ArchiveStore):
        def archive(self, tag, paths):
            # An uploader reporting success without creating bytes is not PASS.
            pass

    prepared(tmp_path / "payload")
    with pytest.raises(RevisionError, match="readback"):
        archive(tmp_path, MissingReadback())


def test_archive_refuses_remote_manifest_collision(tmp_path):
    store = ArchiveStore()
    prepared(tmp_path / "payload")
    first = archive(tmp_path, store)
    altered = copy.deepcopy(first.manifest)
    altered["retention"]["selected_for_app"] = True
    store.objects[(first.tag, "manifest.json")] = canonical(altered)
    with pytest.raises(RevisionError, match="differs"):
        archive(tmp_path, store, state=tmp_path / "new-state")


def test_builder_only_calls_dated_build_and_archive(tmp_path, monkeypatch):
    import app_payload_archive as subject

    store = ArchiveStore()
    observed = {}

    def retained_builder(data, output, **kwargs):
        observed.update(kwargs)
        manifest = prepared(output)
        manifest["source_observation"] = data["source_observation"]
        (output / "manifest.json").write_bytes(canonical(manifest))

    def retained_compute(exports, **kwargs):
        observed.update(kwargs)
        return {}

    monkeypatch.setattr(subject, "_compute_payload", retained_compute)
    monkeypatch.setattr(subject, "_package_payload", retained_builder)
    source = {"observation_date": DAY, "observation_state": "partial",
              "generation_id": "test-retained-fixture", "contract_digest": "a" * 64}
    result = build_and_archive_payload(tmp_path / "exports", state_dir=tmp_path / "state",
        contract_coverage={"failure_provenance_complete": False},
        source_observation=source,
        promotion_reason="unverified_provider_population", repo=REPO, store=store)
    assert observed["tag"] == "archive-staging"
    assert observed["archive_snapshot"] is True and observed["include_history"] is False
    assert result.manifest["retention"]["mode"] == "archive_only"
    assert result.manifest["source_observation"] == source
    assert not list((tmp_path / "state").glob("archive-build-*"))


def test_archive_snapshot_avoids_mutable_inputs_and_other_dates(tmp_path, monkeypatch):
    import app_payload_build as subject

    retained = json.loads((Path(__file__).parent / "fixtures" /
                           "bank_spread_rows_2026-05-19.json").read_bytes())
    cache = tmp_path / "exports/dashboard-cache"
    (cache / DAY).mkdir(parents=True)
    (cache / "latest.json").write_bytes(canonical({"run_date": DAY}))
    (cache / DAY / "banks.json").write_bytes(canonical(retained))

    def forbidden(*_, **__):
        pytest.fail("Archive snapshot touched external history, network, or mutable metadata")

    monkeypatch.setattr(subject.cdr_brand_logos, "fetch_register_logos", forbidden)
    monkeypatch.setattr(subject.rba_decisions, "calendar_payload", forbidden)
    monkeypatch.setattr(subject.rba_official, "load_calendar", forbidden)
    monkeypatch.setattr(subject.app_payload_bank_rates, "embed_bank_rate_history", forbidden)
    monkeypatch.setattr(subject, "load_brand_shortcodes", forbidden)
    monkeypatch.setattr("app_payload_bank_rate_source.require_selected_current_export", forbidden)
    data = subject._compute_payload(tmp_path / "exports", archive_snapshot=True)
    assert data["core"]["run_date"] == DAY
    assert sum(len(v["rates"]) for v in data["core"]["sections"].values()) > 0
    assert data["bank_history"] is None and data["history_banks"] is None
    assert "rba" not in data["core"] and "brands" not in data["core"]
