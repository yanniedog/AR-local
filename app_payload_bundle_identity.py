"""Pure existing bundle hash calculation; callers own manifest validation.

This function grants no publication or inventory authority. Legacy publishers
must keep their existing validate_manifest gate; detached-evidence callers must
validate the financial base and bound references before invoking it.
"""
import hashlib
import json

from app_payload_bank_history_asset import NAMESPACE


def manifest_bundle_sha256(manifest):
    value = {key: val for key, val in manifest.items()
             if key not in {"generated_at", "tag", "payload_revision", "files"}}
    value["files"] = {key: {k: v for k, v in entry.items() if k != "url"}
                      for key, entry in manifest["files"].items()}
    if NAMESPACE in value:
        namespace = value[NAMESPACE]
        value[NAMESPACE] = {**namespace, "file": {
            key: val for key, val in namespace["file"].items() if key != "url"}}
    if "public_rate_catalogue" in value:
        from app_payload_public_rates import identity_namespace
        value["public_rate_catalogue"] = identity_namespace(value["public_rate_catalogue"])
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
