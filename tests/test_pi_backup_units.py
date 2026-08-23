"""Static safety contract for opt-in Pi backup systemd wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy/pi"


def read(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def test_backup_services_require_the_external_mount_and_configuration() -> None:
    for name in ("ar-local-backup.service", "ar-local-restore-drill.service"):
        unit = read(name)
        assert "RequiresMountsFor=/mnt/ar-local-backup" in unit
        assert "ConditionPathExists=/etc/ar-local/backup.env" in unit
        assert "User={{AR_LOCAL_USER}}" in unit
        assert "Documentation=file://{{AR_LOCAL_REPO}}/docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md" in unit
        assert "app-payload.env" not in unit


def test_installation_is_explicit_and_preflight_precedes_enable() -> None:
    installer = read("install-backup-foundation.sh")
    preflight = installer.index("pi_backup_foundation.py\" preflight")
    enable = installer.index("systemctl enable --now")
    assert preflight < enable
    assert "sudo -u \"$run_user\" test -r \"$config\"" in installer
    assert "ar-local-backup.timer ar-local-restore-drill.timer" in installer
    runtime_apply = read("apply-pi-runtime-units.sh")
    assert "ar-local-backup.timer" not in runtime_apply
    assert "ar-local-restore-drill.timer" not in runtime_apply


def test_configuration_has_controlled_plan_identity_and_no_force_bypass() -> None:
    example = read("backup.env.example")
    assert "AR_BACKUP_PLAN_GIT_COMMIT=4a3af1ccbdc24deefe3d12da2f7152946984f459" in example
    assert "AR_BACKUP_PLAN_SHA256=510937fc4d09d0e9066c5830fedd80053c9d3c40a062c34c8acce764f1fa8adc" in example
    assert "AR_BACKUP_PLAN_RAW_SHA256=0e40cba6682f0bd95bc48e2df044e387ebfeaa1a2a3e590145507a03cbf94d7c" in example
    implementation = (ROOT / "pi_backup_foundation.py").read_text(encoding="utf-8")
    policy = (ROOT / "ar_local_backup_policy.py").read_text(encoding="utf-8")
    assert "allow-unmounted" not in implementation.lower()
    assert "allow-unmounted" not in policy.lower()
    deployment_schema = (ROOT / "contracts/pi-deployment-acceptance-v1.schema.json").read_text(
        encoding="utf-8"
    )
    assert '"previous_record_sha256"' in deployment_schema
    assert '"candidate_code_sha"' in deployment_schema


def test_timers_run_outside_the_ingest_window() -> None:
    assert "04:00:00 Australia/Hobart" in read("ar-local-backup.timer")
    assert "Sun *-*-* 08:00:00 Australia/Hobart" in read("ar-local-restore-drill.timer")
    assert "Persistent=true" in read("ar-local-backup.timer")
    assert "Persistent=true" in read("ar-local-restore-drill.timer")
