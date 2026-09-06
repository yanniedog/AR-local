"""Resolve unfinished-run products by stable ID instead of mutable product names."""

from __future__ import annotations

import json
from pathlib import Path

from cdr_compatibility import response_shape_error
from cdr_http_policy import DEFAULT_HTTP_POLICY


def existing_product_leaves(root: Path, provider: str) -> tuple[dict[str, Path], set[str]]:
    leaves: dict[str, Path] = {}
    conflicts: set[str] = set()
    for dataset in ("Mortgage", "Savings", "TD"):
        for path in (root / dataset / provider).glob("*/*/product-id.txt"):
            try:
                if path.stat().st_size > DEFAULT_HTTP_POLICY.max_url_chars:
                    continue
                pid = path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError):
                continue
            if not pid:
                continue
            if pid in leaves and leaves[pid] != path.parent:
                conflicts.add(pid)
            else:
                leaves[pid] = path.parent
    return leaves, conflicts


def usable_cached_detail(leaf: Path, product_id: str) -> bool:
    path = leaf / "product-detail.json"
    try:
        if path.stat().st_size > DEFAULT_HTTP_POLICY.max_body_bytes:
            return False
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return (
            isinstance(parsed, dict) and not parsed.get("errors")
            and not parsed.get("errorCode") and not parsed.get("errorMessage")
            and response_shape_error(parsed, phase="product_detail", product_id=product_id) is None
        )
    except (OSError, ValueError):
        return False
