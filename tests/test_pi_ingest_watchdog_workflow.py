"""Static safety contract for the GitHub-side ingest freshness watchdog."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pi-ingest-watchdog.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_schedule_runs_once_off_the_hour_without_a_runner_time_gate() -> None:
    text = _workflow_text()

    assert text.count("- cron:") == 1
    assert '- cron: "17 17 * * *"' in text
    assert "workflow_dispatch:" in text
    assert "date +%H" not in text
    assert "steps.gate.outputs" not in text


def test_watchdog_is_notification_only_and_cannot_touch_the_pi() -> None:
    text = _workflow_text()

    assert "contents: read" in text
    assert "issues: write" in text
    assert "scripts/pi_ingest_manifest_check.py" in text
    assert "ssh " not in text.casefold()
    assert "systemctl" not in text.casefold()
    assert "pi_deploy_verify.py" not in text
