"""SMTP email notifications for AR-local Pi operations."""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Optional


DEFAULT_NOTIFY_ENV = Path("/etc/ar-local/notify.env")


def load_notify_env(path: Optional[Path] = None) -> dict[str, str]:
    env_path = path or Path(os.environ.get("AR_LOCAL_NOTIFY_ENV", str(DEFAULT_NOTIFY_ENV)))
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _merged_config(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    merged = load_notify_env()
    for key, value in os.environ.items():
        if key.startswith("AR_LOCAL_"):
            merged[key] = value
    if extra:
        merged.update(extra)
    return merged


def notify_recipients(config: dict[str, str]) -> list[str]:
    raw = config.get("AR_LOCAL_NOTIFY_TO", "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def smtp_settings(config: dict[str, str]) -> tuple[str, int, str, str, str]:
    host = config.get("AR_LOCAL_SMTP_HOST", "").strip()
    user = config.get("AR_LOCAL_SMTP_USER", "").strip()
    password = config.get("AR_LOCAL_SMTP_PASS", "").strip()
    port_text = config.get("AR_LOCAL_SMTP_PORT", "587").strip()
    sender = config.get("AR_LOCAL_SMTP_FROM", user).strip() or user
    if not host or not user or not password:
        return "", 587, "", "", ""
    try:
        port = int(port_text)
    except ValueError:
        port = 587
    return host, port, user, password, sender


def email_configured(config: Optional[dict[str, str]] = None) -> bool:
    cfg = config or _merged_config()
    host, _, user, password, _ = smtp_settings(cfg)
    return bool(host and user and password and notify_recipients(cfg))


def send_email(
    subject: str,
    body: str,
    *,
    to_addrs: Optional[Iterable[str]] = None,
    config: Optional[dict[str, str]] = None,
) -> bool:
    """Send a plain-text email. Returns True when sent, False when SMTP is not configured."""
    cfg = config or _merged_config()
    recipients = list(to_addrs) if to_addrs is not None else notify_recipients(cfg)
    host, port, user, password, sender = smtp_settings(cfg)
    if not recipients:
        print("[email_notify] skipped: AR_LOCAL_NOTIFY_TO not set")
        return False
    if not host or not user or not password:
        print("[email_notify] skipped: SMTP host/user/pass not configured")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as smtp:
            smtp.login(user, password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            if port != 25:
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(message)
    print(f"[email_notify] sent subject={subject!r} to={recipients}")
    return True
