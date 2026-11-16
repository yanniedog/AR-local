from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scripts/pi_storage_inventory.sh"
DEDUPE = ROOT / "scripts/pi_export_stage_dedupe.sh"


def test_storage_inventory_records_symlink_paths_and_targets():
    script = INVENTORY.read_text(encoding="utf-8")
    assert 'printf \'%s\\n\' "$link"' in script
    assert 'realpath -m -- "$link"' in script
    assert "link_targets symlink-system /etc /usr/local /home /root -maxdepth 6" in script
    assert "link_targets symlink-sibling /srv/ar-local /var/lib -maxdepth 4" in script


def test_delete_mode_requires_exact_queue_task_cgroup():
    script = DEDUPE.read_text(encoding="utf-8")
    assert r"grep -Eq '/ar-local-queue-task-[0-9a-f]{32}\.service$'" in script
    assert "grep -q 'ar-local-queue-task-'" not in script


def test_delete_mode_blocks_active_daily_watchdog():
    script = DEDUPE.read_text(encoding="utf-8")
    blocked_units = script.split("for u in ", 1)[1].split("; do", 1)[0]
    assert "ar-local-daily-watchdog.service" in blocked_units


def test_each_finalized_candidate_marker_is_verified_and_contained():
    script = DEDUPE.read_text(encoding="utf-8")
    assert 'sys.stdout.write(p + "\\0" + marker["out_dir"] + "\\0")' in script
    assert "verify_completion_marker(marker, state, day) is not True" in script
    assert "candidate = Path(recorded_path).resolve(strict=True)" in script
    assert "day_root.parent != runs_root" in script
    assert "day_root not in candidate.parents" in script
    assert 'candidate=$(verified_out_dir "$day" "$marker" "$cand") || continue' in script
    assert script.index('candidate=$(verified_out_dir "$day" "$marker" "$cand")') < script.index(
        'identical_subset "$dir/_exports" "$candidate"'
    )


def test_storage_scripts_have_valid_bash_syntax():
    for script in (INVENTORY, DEDUPE):
        subprocess.run(["bash", "-n", str(script)], check=True)
