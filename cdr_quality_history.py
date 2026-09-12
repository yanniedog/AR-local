"""Full membership comparisons across every retained observation, without rewriting history."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta


def history_context(results: list[dict], current: dict | None) -> dict:
    by_date: dict[str, list[dict]] = defaultdict(list)
    seen_products, provider_days, failures = {}, defaultdict(set), defaultdict(dict)
    for row in sorted(results, key=lambda r: (r["run_date"], r["key"])):
        by_date[row["run_date"]].append(row)
        for identity, product in row["products"].items():
            previous = seen_products.get(identity)
            if previous is None or previous["last_seen"] <= row["run_date"]:
                seen_products[identity] = {**product, "first_seen": (previous or {}).get("first_seen", row["run_date"]),
                                          "last_seen": row["run_date"], "source": row["key"]}
            provider_days[str(product["provider"])].add(row["run_date"])
        for provider, count in (row["status"].get("by_provider") or {}).items():
            failures[provider][row["key"]] = {"run_date": row["run_date"], "failures": count}
    dates = sorted(by_date)
    missing_dates = []
    if dates:
        cursor, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
        while cursor <= last:
            if cursor.isoformat() not in by_date:
                missing_dates.append(cursor.isoformat())
            cursor += timedelta(days=1)
    membership = (current or {}).get("products", {})
    absent = {key: value for key, value in seen_products.items() if key not in membership}
    previous_dates = [d for d in dates if current and d < current["run_date"]]
    previous_products = {}
    if previous_dates:
        for row in by_date[previous_dates[-1]]:
            previous_products.update(row["products"])
    # Every revision is compared with the selected generation, never silently
    # flattened into one daily count. Absence alone is not proof of data loss.
    revisions = []
    for row in by_date.get((current or {}).get("run_date"), []):
        old = row["products"]
        revisions.append({"source": row["key"], "generation_id": row["generation_id"],
                          "added_in_selected": sorted(set(membership) - set(old)),
                          "absent_in_selected": sorted(set(old) - set(membership)),
                          "changed_in_selected": sorted(k for k in old.keys() & membership.keys()
                                                        if old[k]["sha256"] != membership[k]["sha256"]),
                          "rates_delta": (current or row)["accounting"]["source_rates"] - row["accounting"]["source_rates"]})
    return {
        "observation_count": len(results), "date_count": len(dates), "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None, "missing_retained_dates": missing_dates,
        "unique_products_ever": len(seen_products), "products_absent_from_selected": absent,
        "absent_since_previous_observed_day": sorted(set(previous_products) - set(membership)),
        "providers_ever": {p: {"days": len(ds), "first": min(ds), "last": max(ds)} for p, ds in provider_days.items()},
        "failure_recurrence": dict(failures), "same_day_revision_comparisons": revisions,
        "absence_semantics": "Unconfirmed: investigate expiry, provider/category changes, request failures and register history before calling this lost coverage.",
    }
