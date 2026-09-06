"""Authenticate a user-owned receiver's exact production-release transition."""
from __future__ import annotations

import os
import re
from pathlib import Path


def validate_previous(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"production_sha", "receiver_sha", "record_sha256"}:
        raise ValueError("previous runtime identity is incomplete")
    for key, width in (("production_sha", 40), ("receiver_sha", 40), ("record_sha256", 64)):
        if not isinstance(value[key], str) or not re.fullmatch(rf"[0-9a-f]{{{width}}}", value[key]):
            raise ValueError("previous runtime identity is invalid")
    return value


def authority(args) -> dict:
    """No CLI escape hatch: authority comes from the pinned ordinary-user config."""
    if not getattr(args, "user_runtime_transition", False):
        return {}
    import laptop_backup_user_session as user
    expected = os.environ.get("AR_USER_BACKUP_CONFIG_SHA256")
    if not expected:
        raise ValueError("runtime transition requires the verified user-session runner")
    config = user.load_config(Path(user.__file__).resolve().parent.parent / user.CONFIG_NAME, expected)
    user.verify_release(config)
    if (str(args.target) != config["target"] or args.candidate_code_sha != config["candidate_sha"]
            or args.protected_code_sha != config["protected_sha"]
            or args.operator != config["operator_sid"]):
        raise ValueError("runtime transition differs from the pinned configuration")
    return validate_previous(config.get("previous_runtime"))


def lineage_fields(args) -> dict:
    return {
        "runtime_predecessor": authority(args),
        "allowed_predecessor_candidates": tuple(getattr(args, "allowed_predecessor_candidate_sha", ())),
    }
