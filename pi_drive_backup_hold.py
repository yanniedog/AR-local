"""Persistent operator hold checked before every Drive dispatch and acceptance.

No expiry or automatic release exists. Only explicit operator approval permits
removing a hold. Queue requests remain durable while the hold is active.
"""
from __future__ import annotations

import os
from pathlib import Path

SYSTEM_HOLD = Path('/etc/ar-local/drive-write-hold.json')
GLOBAL_LOCK_NAME = '.drive-write-hold-activation.lock'
GUARD_PROTOCOL = 'ar-drive-global-dispatch-guard-v1'
SPOOL_HOLD_NAME = 'write-hold.json'


class Blocked(RuntimeError):
    """Shared refusal type, including when the backup CLI runs as __main__."""


def hold_state(spool: Path) -> dict | None:
    """Existence alone blocks, including malformed and dangling-link markers.

    Never parse a marker's contents to decide whether writes are allowed: an
    empty or interrupted marker must still protect the fallback snapshot.
    The system marker cannot be bypassed with an alternate spool or --force.
    """
    markers = ((SYSTEM_HOLD, 'HELD'),
               (SYSTEM_HOLD.parent / GLOBAL_LOCK_NAME, 'ACTIVATION_PENDING'),
               (spool / SPOOL_HOLD_NAME, 'HELD'))
    for path, state in markers:
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        except OSError:
            return {'state': 'UNKNOWN_BLOCKED', 'path': str(path),
                    'reason': 'Google Drive write hold cannot be checked: ' + str(path)}
        return {'state': state, 'path': str(path),
                'coordination': 'NOT_ATTESTED_BY_EXISTENCE_CHECK',
                'reason': 'Google Drive writes held pending explicit operator approval: ' + str(path)}
    return None


def hold_reason(spool: Path) -> str | None:
    state = hold_state(spool)
    return state['reason'] if state else None


def require_writes_allowed(spool: Path) -> None:
    reason = hold_reason(spool)
    if reason:
        raise Blocked(reason)
