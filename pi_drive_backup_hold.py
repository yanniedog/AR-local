"""Persistent operator hold checked before every Drive dispatch and acceptance.

No expiry or automatic release exists. Only explicit operator approval permits
removing a hold. Queue requests remain durable while the hold is active.
"""
from __future__ import annotations

import os
from pathlib import Path

SYSTEM_HOLD = Path('/etc/ar-local/drive-write-hold.json')
SPOOL_HOLD_NAME = 'write-hold.json'


class Blocked(RuntimeError):
    """Shared refusal type, including when the backup CLI runs as __main__."""


def hold_reason(spool: Path) -> str | None:
    """Existence alone blocks, including malformed and dangling-link markers.

    Never parse a marker's contents to decide whether writes are allowed: an
    empty or interrupted marker must still protect the fallback snapshot.
    The system marker cannot be bypassed with an alternate spool or --force.
    """
    for path in (SYSTEM_HOLD, spool / SPOOL_HOLD_NAME):
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError:
            return 'Google Drive write hold cannot be checked: ' + str(path)
        return 'Google Drive writes held pending explicit operator approval: ' + str(path)
    return None


def require_writes_allowed(spool: Path) -> None:
    reason = hold_reason(spool)
    if reason:
        raise Blocked(reason)
