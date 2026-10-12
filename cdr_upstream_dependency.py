"""Recognize retained public-API evidence of a server's own dependency failure."""
from __future__ import annotations

import json


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("ambiguous dependency error object")
        value[key] = item
    return value


def dependency_failure_evidence(status, text: str) -> str | None:
    """Keep the evidenced tenant-token outage distinct from client credentials.

    Neither a generic 401 nor a mention of a token is sufficient. Mixed errors
    retain the normal authentication policy. The compact envelope is itself
    classifiable; original response bytes remain in the raw attempt journal.
    """
    if str(status) != "401":
        return None
    try:
        value = json.loads(str(text or "")[:65536], object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != {"errors"}:
        return None
    errors = value["errors"]
    if not isinstance(errors, list) or len(errors) != 1 or not isinstance(errors[0], dict):
        return None
    error = errors[0]
    if (set(error) != {"code", "title", "detail", "meta"}
            or error.get("code") != "EBAU001"
            or error.get("title") != "Error while fetching token"
            or error.get("detail") != "Error while fetching the authorisation token for the given tenantId"
            or error.get("meta") != {"urn": "urn:au-cds:error:cds-all:GeneralError/Expected"}):
        return None
    compact = {key: error[key] for key in ("code", "title", "detail", "meta")}
    return json.dumps({"errors": [compact]}, separators=(",", ":"))
