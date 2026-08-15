from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_notify_credentials_are_readable_only_by_root_and_service_group() -> None:
    installer = (ROOT / "deploy/pi/install-ingest-notify.sh").read_text(encoding="utf-8")
    systemd_installer = (ROOT / "deploy/pi/install-pi-systemd.sh").read_text(encoding="utf-8")

    assert 'install -o root -g "$run_group" -m 0640' in installer
    assert 'chown "root:$run_group" "$env_file"' in installer
    assert 'chmod 0640 "$env_file"' in installer
    assert 'install-ingest-notify.sh" "$repo_dir" "$run_group"' in systemd_installer
