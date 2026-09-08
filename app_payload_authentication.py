"""Keep attributable bank authentication failures out of publication budgets."""

from __future__ import annotations

from typing import Any, Mapping


AUTHENTICATION_CATEGORIES = frozenset({"public_endpoint_auth_required", "access_denied"})


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("failure accounting must use nonnegative integers")
    return value


def _provider_exclusions(providers: list, coverage: Mapping[str, Any]) -> dict:
    result = {"failure_records": 0, "providers_partial": 0, "providers_failed": 0, "providers": []}
    totals = {"failure_records": 0, "providers_partial": 0, "providers_failed": 0}
    identities = set()
    for provider in providers:
        if not isinstance(provider, Mapping):
            raise ValueError("invalid provider accounting")
        identity = provider.get("provider_uid")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("invalid or duplicate provider identity")
        identities.add(identity)
        failures = _count(provider.get("failure_records"))
        state = provider.get("state")
        if state not in {"complete", "empty", "partial", "failed"}:
            raise ValueError("provider was not attempted")
        totals["failure_records"] += failures
        if state in {"partial", "failed"}:
            totals[f"providers_{state}"] += 1
        categories = provider.get("failure_categories", {})
        if not isinstance(categories, Mapping):
            raise ValueError("invalid failure categories")
        counts = {name: _count(count) for name, count in categories.items()}
        if "failure_categories" in provider and sum(counts.values()) != failures:
            raise ValueError("failure categories do not reconcile")
        auth = sum(count for name, count in counts.items() if name in AUTHENTICATION_CATEGORIES)
        if not auth:
            continue
        if state not in {"partial", "failed"}:
            raise ValueError("authentication failure on a complete provider")
        result["failure_records"] += auth
        # Mixed failures remain subject to the provider budget. Never exempt a
        # holder's unrelated failures just because it also rejected credentials.
        if auth == failures:
            result[f"providers_{state}"] += 1
        result["providers"].append({
            "provider_uid": identity,
            "provider": provider.get("brand_name") or provider.get("provider_dir") or identity,
            "failure_records": auth,
            "authentication_only": auth == failures,
        })
    if len(identities) != _count(coverage.get("providers_attempted")):
        raise ValueError("provider population does not reconcile")
    if any(total != _count(coverage.get(name)) for name, total in totals.items()):
        raise ValueError("failure totals do not reconcile")
    return result


def authentication_exclusions(contract: Mapping[str, Any]) -> dict:
    """Use only reconciled, contract-bound classification; old contracts stay valid.

    Missing historical classifications grant no exemption. The gate still
    requires intact provenance, register coverage and a nonempty real catalogue.
    """
    empty = {"failure_records": 0, "providers_partial": 0, "providers_failed": 0, "providers": []}
    coverage, providers = contract.get("coverage"), contract.get("provider_states")
    if not isinstance(coverage, Mapping) or not isinstance(providers, list):
        return empty
    try:
        return _provider_exclusions(providers, coverage)
    except (TypeError, ValueError):
        return empty
