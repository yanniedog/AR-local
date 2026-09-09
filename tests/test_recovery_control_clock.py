"""Real recovery-monitor clock changes must not invalidate control backups."""
import json
from pathlib import Path

import pytest
import pi_laptop_backup_source as source
import laptop_backup_scheduled as scheduled


def test_real_recovery_tick_preserves_control_revision_but_state_changes_do_not():
    import copy
    report = json.loads((Path(__file__).parents[1] /
        "docs/evidence/private-tools-activation-20260910/control-status-comparison.json").read_bytes())
    assert report["changed_fields"] == ["checked_at"]
    before, after = report["previous"], report["current"]
    normalized = source.recovery_status_content(before)
    assert normalized == source.recovery_status_content(after)
    manifest = {"kind": "control", "files": [{"path": "data/state/cdr-recovery-status.json",
        "size": 10, "sha256": "a" * 64}]}
    manifest["control"] = {"repositories": [], "recovery_status": normalized}
    first = source.content_revision(manifest)
    manifest["files"][0].update(size=11, sha256="b" * 64)
    assert source.content_revision(manifest) == scheduled.content_revision(manifest) == first
    for field in normalized:
        changed = copy.deepcopy(manifest)
        changed["control"]["recovery_status"][field] = "changed"
        if field == "schema_version":
            with pytest.raises(ValueError, match="identity"):
                source.content_revision(changed)
        else:
            assert source.content_revision(changed) != first, field
    changed = copy.deepcopy(manifest)
    changed["control"]["recovery_status"]["new_recovery_fact"] = 1
    assert source.content_revision(changed) != first
    # Historical manifests keep their original byte-based identity.
    del manifest["control"]["recovery_status"]
    old = source.content_revision(manifest)
    manifest["files"][0]["sha256"] = "c" * 64
    assert source.content_revision(manifest) != old


@pytest.mark.parametrize("checked", [None, "bad", "2026-09-10T09:00:00"])
def test_recovery_status_normalization_rejects_invalid_clock(checked):
    with pytest.raises(ValueError):
        source.recovery_status_content({"schema_version": 1, "checked_at": checked})
