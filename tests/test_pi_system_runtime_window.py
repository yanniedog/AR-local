"""Image budget/current-manifest contracts; no Pi or process-control effects."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from pi_plain_backup_core import Blocked
import pi_system_guard_host as host
import pi_system_guard_packet as builder
import pi_system_guard_plan as service
import pi_system_guard_policy as policy
import pi_system_guard_resources as resources
from pi_shared_queue_policy import admission
from tests.shared_pi_queue_fixtures import record
from tests.test_pi_system_guard import NONCE, NOW, packet


def test_actual_late_evening_image_reservation_uses_clipped_budget_and_wait_zero():
    body = packet("archive")
    start = datetime(2026, 10, 24, 18, 45, tzinfo=ZoneInfo("Australia/Hobart")).astimezone(timezone.utc)
    end = builder.expiry_for("archive", start)
    body.update(created_at=start.isoformat(), expires_at=end.isoformat(), runtime_seconds=int((end-start).total_seconds()))
    policy.validate(body, NONCE, start)
    plan = service.service_plan(NONCE, "archive", packet=body)
    assert body["runtime_seconds"] == 20399
    assert plan["properties"]["RuntimeMaxSec"] == "20399"
    assert plan["properties"]["TimeoutStartSec"] == "60"
    assert plan["argv"][plan["argv"].index("--wait-timeout") + 1] == "0"
    job = record(unit=body["unit"], resources=["ar-local", "host"], max_duration_seconds=20399, ready_since=start.isoformat())
    assert admission(job, [job], start) == (True, "admitted")
    assert admission({**job, "max_duration_seconds": 21600}, [], start) == (False, "would-cross-ingest-start")
    assert service.service_plan(NONCE, "archive", packet=plan["runtime_inputs"]) == plan


@pytest.mark.parametrize("phase", sorted(policy.PHASES))
def test_every_image_phase_binds_the_same_frozen_runtime_and_immediate_admission(phase):
    body = packet(phase)
    plan = service.service_plan(NONCE, phase, packet=body)
    assert plan["properties"]["RuntimeMaxSec"] == str(body["runtime_seconds"])
    assert plan["argv"][plan["argv"].index("--max-runtime") + 1] == str(body["runtime_seconds"])
    assert plan["argv"][plan["argv"].index("--wait-timeout") + 1] == "0"


@pytest.mark.parametrize("runtime", [None, True, 14, 119, 121, 21601, "120", 120.0])
def test_image_cannot_accept_missing_or_independently_shortened_runtime(runtime):
    body = packet()
    if runtime is None: body.pop("runtime_seconds")
    else: body["runtime_seconds"] = runtime
    with pytest.raises(Blocked): policy.validate(body, NONCE, NOW)
    with pytest.raises(Blocked): service.service_plan(NONCE, "PROBE", packet=body)


def test_image_attestation_deadline_cannot_extend_chosen_or_absolute_window(monkeypatch):
    body = packet("compress")
    monkeypatch.setattr(resources.time, "monotonic", lambda: 100.0)
    controller = SimpleNamespace(process_identity=lambda pid: {}, boot=lambda: "boot", now=lambda: NOW + timedelta(seconds=30))
    assert resources.context(controller, body, {})["deadline_monotonic"] == 190.0


def test_image_manifest_path_never_falls_back_to_the_plain_controller_manifest(monkeypatch):
    body = packet()
    paths = []
    def digest(path):
        paths.append(path)
        return "d" * 64 if path == host.ROOT / "root-control-manifest.json" else body["root_control_manifest_sha256"]
    monkeypatch.setattr(host, "digest", digest)
    monkeypatch.setattr(host, "approval", lambda *args, **kwargs: pytest.fail("wrong own manifest must fail first"))
    with pytest.raises(Blocked, match="own current root control manifest"):
        host.ImageHost(NONCE)._controls(body)
    assert paths == [host.ROOT / "root-control-manifest.json"]


@pytest.mark.parametrize("changed", ["runtime", "manifest", "schema", "phase", "nonce", "boot", "completion"])
def test_image_requires_actual_current_manifest_probe_not_an_old_or_foreign_proof(changed):
    current, previous = packet("build"), packet()
    proof = {"schema": "ar-local-system-recovery-coupled-probe-v1", "nonce": NONCE, "result": "IMAGE_PROBE_PASS",
             "boot_id": "current-boot", "root_completion_verified": True,
             "source_closure_sha256": current["source_closure_sha256"],
             "root_control_manifest_sha256": current["root_control_manifest_sha256"]}
    policy.validate_commissioning(current, NONCE, previous, proof, "current-boot")
    if changed == "runtime": previous.pop("runtime_seconds")
    elif changed == "manifest": previous["root_control_manifest_sha256"] = "d" * 64
    elif changed == "schema": proof["schema"] = "ar-local-plain-backup-coupled-probe-v1"
    elif changed == "phase": previous["phase"] = "archive"
    elif changed == "nonce": proof["nonce"] = "d" * 32
    elif changed == "boot": proof["boot_id"] = "old-boot"
    else: proof["root_completion_verified"] = False
    with pytest.raises(Blocked): policy.validate_commissioning(current, NONCE, previous, proof, "current-boot")
