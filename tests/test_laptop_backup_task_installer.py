from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_task_registration_fails_closed_and_read_back_is_verified() -> None:
    script = (ROOT / "install_laptop_backup_task.ps1").read_text(encoding="utf-8")

    registration = (
        "Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force "
        "-ErrorAction Stop"
    )
    assert registration in script
    assert "Scheduled task registration failed" in script
    assert script.index(registration) < script.index("$registered = Get-ScheduledTask")
    assert "Scheduled task read-back verification failed" in script
    assert "principal identity" in script
    assert "registeredActions[0].Arguments -ne $arguments" in script
    assert script.index("Scheduled task read-back verification failed") < script.index(
        "[pscustomobject]@{"
    )
