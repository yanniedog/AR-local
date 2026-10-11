"""Static safety contract for the GitHub-side ingest freshness watchdog."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pi-ingest-watchdog.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_schedule_runs_twice_hourly_without_a_runner_time_gate() -> None:
    text = _workflow_text()

    assert text.count("- cron:") == 1
    assert '- cron: "17,47 * * * *"' in text
    assert "workflow_dispatch:" in text
    assert "date +%H" not in text
    assert "steps.gate.outputs" not in text
    assert "group: pi-ingest-watchdog" in text
    assert "cancel-in-progress: false" in text
    assert "timeout-minutes: 10" in text


def test_watchdog_is_notification_only_and_cannot_touch_the_pi() -> None:
    text = _workflow_text()

    assert "contents: read" in text
    assert "issues: write" in text
    assert "scripts/pi_ingest_cloud_incident.py" in text
    assert "--expected-tz" not in text
    assert "ssh " not in text.casefold()
    assert "systemctl" not in text.casefold()
    assert "pi_deploy_verify.py" not in text


def test_failed_setup_and_checker_still_retain_unknown_evidence() -> None:
    text = _workflow_text()
    assert text.count("if: always()") == 2
    assert '"status":"UNKNOWN"' in text
    assert '"reason":"CHECK_INFRASTRUCTURE_FAILED"' in text
    assert "--checker-unavailable" in text
    assert "actions/upload-artifact@v4" in text
    assert "path: check.json" in text
    assert "if-no-files-found: error" in text
    assert "|| true" not in text
