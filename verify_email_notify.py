"""Self-test for ar_local_email_notify configuration helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

from ar_local_email_notify import email_configured, load_notify_env, notify_recipients, send_email


def test_load_notify_env() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        env_path = Path(tmp) / "notify.env"
        env_path.write_text(
            "\n".join(
                [
                    "# comment",
                    "AR_LOCAL_NOTIFY_TO=jkokavec@gmail.com, ops@example.com",
                    'AR_LOCAL_SMTP_HOST="smtp.gmail.com"',
                    "AR_LOCAL_SMTP_PORT=587",
                    "AR_LOCAL_SMTP_USER=user@gmail.com",
                    "AR_LOCAL_SMTP_PASS=secret",
                ]
            ),
            encoding="utf-8",
        )
        cfg = load_notify_env(env_path)
        assert notify_recipients(cfg) == ["jkokavec@gmail.com", "ops@example.com"]
        assert cfg["AR_LOCAL_SMTP_HOST"] == "smtp.gmail.com"
        assert email_configured(cfg)


def test_send_email_skips_without_smtp() -> None:
    assert send_email("subject", "body", config={}) is False


def main() -> int:
    test_load_notify_env()
    test_send_email_skips_without_smtp()
    print("verify_email_notify: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
