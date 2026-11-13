"""Bounded, read-only Pi coverage diagnostics; no URLs or response bodies emitted."""
import collections
import json
import os
import re
import sys

MAX_PROVIDERS = 512
MAX_REQUESTS = 8192
DENIED = []


def safe(value, limit=80):
    text = str(value if value is not None else "unknown")
    text = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+", "<url>", text)
    text = re.sub(r"[A-Za-z0-9_/+=-]{40,}", "<redacted>", text)
    return re.sub(r"[\x00-\x1f\x7f]", " ", text)[:limit]


def load(path, limit=4 << 20):
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
        return json.loads(data) if len(data) <= limit else None
    except (OSError, ValueError):
        return None


def find(root, names, depth=4):
    hits = {}
    for cur, dirs, files in os.walk(root, onerror=DENIED.append):
        if len(os.path.relpath(cur, root).split(os.sep)) >= depth and cur != root:
            dirs[:] = []
        for name in names.intersection(files):
            hits.setdefault(name, []).append(os.path.join(cur, name))
    return hits


def count(value):
    return value if type(value) is int and value >= 0 else None


def counts(value):
    if not isinstance(value, dict) or len(value) > MAX_PROVIDERS:
        return None
    if any(not isinstance(k, str) or count(v) is None for k, v in value.items()):
        return None
    return value


def provider_names(status):
    aliases, states = {}, {}
    rows = status.get("provider_states")
    rows = rows if isinstance(rows, list) else []
    for row in rows[:MAX_PROVIDERS]:
        if not isinstance(row, dict):
            continue
        name = row.get("brand_name") or row.get("provider_dir") or row.get("provider_uid")
        if not isinstance(name, str):
            continue
        for key in (row.get("provider_dir"), row.get("provider_uid"), name):
            if isinstance(key, str):
                aliases[key] = name
        if count(row.get("failure_records")) is not None:
            states[name] = states.get(name, 0) + row["failure_records"]
    return aliases, states


def status_report(status):
    """Counts are aggregates; unresolved requests are a separate deduplicated sample."""
    status = status if isinstance(status, dict) else {}
    aliases, state_counts = provider_names(status)
    raw_counts = counts(status.get("by_provider"))
    if raw_counts is None and "by_provider" not in status and state_counts:
        raw_counts = state_counts
    provider_counts = collections.Counter()
    for name, number in (raw_counts or {}).items():
        provider_counts[safe(aliases.get(name, name), 64)] += number
    total = count(status.get("total"))
    known = (total is not None and raw_counts is not None and
             sum(raw_counts.values()) == total and
             status.get("failure_provenance_complete") is not False)
    samples = collections.Counter()
    requests = status.get("unresolved_requests")
    request_schema_known = isinstance(requests, list)
    requests = requests if request_schema_known else []
    malformed = 0
    for row in requests[:MAX_REQUESTS]:
        if not isinstance(row, dict):
            malformed += 1
            continue
        name = next((row.get(key) for key in ("provider_dir", "provider_uid", "bank", "provider", "brand_name", "brand")
                     if isinstance(row.get(key), str) and row[key]), None)
        if name is None:
            malformed += 1
            continue
        key = (safe(aliases.get(name, name), 64), safe(row.get("phase"), 32),
               safe(row.get("failure_category") or row.get("category"), 40), safe(row.get("status"), 40))
        samples[key] += 1
    categories = {}
    raw_categories = status.get("by_provider_failure_category")
    if isinstance(raw_categories, dict):
        for name, values in list(raw_categories.items())[:MAX_PROVIDERS]:
            if counts(values) is not None:
                target = categories.setdefault(safe(aliases.get(name, name), 64), collections.Counter())
                target.update({safe(k, 40): v for k, v in values.items()})
    return {"total": total if known else None, "reported_total": total,
            "providers": dict(provider_counts), "categories": categories, "samples": samples,
            "sample_complete": request_schema_known and status.get("unresolved_requests_complete") is True and
                               len(requests) <= MAX_REQUESTS and not malformed,
            "sample_unknown": malformed, "capped": len(requests) > MAX_REQUESTS,
            "aggregates": {field: {safe(k, 40): v for k, v in (counts(status.get(field)) or {}).items()}
                           for field in ("by_phase", "by_status", "by_failure_category")}}


def journal_report(path):
    """Use one known journal, never sum natural/revision copies of the same failures."""
    rows, providers = [], collections.Counter()
    known, capped = True, False
    try:
        with open(path, "rb") as handle:
            for index in range(5001):
                line = handle.readline((64 << 10) + 1)
                if not line:
                    break
                if index == 5000 or len(line) > 64 << 10:
                    known, capped = False, True
                    break
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    known = False
                    continue
                if not isinstance(row, dict) or not isinstance(row.get("bank"), str):
                    known = False
                    continue
                providers[row["bank"]] += 1
                rows.append(row)
    except OSError as error:
        DENIED.append(error)
        known = False
    report = status_report({"total": sum(providers.values()), "by_provider": dict(providers),
                            "unresolved_requests": rows, "unresolved_requests_complete": known,
                            "failure_provenance_complete": known})
    report["capped"] = capped
    return report


def shape(node):
    if not isinstance(node, dict):
        return type(node).__name__
    return {safe(k, 40): (v if isinstance(v, (int, float, bool, type(None))) else
                          type(v).__name__ + ("[%d]" % len(v) if isinstance(v, (list, dict)) else ""))
            for k, v in list(node.items())[:60]}


def day_report(root):
    hits = find(root, {"provider-population-report.json"})
    status = load(os.path.join(root, "_exports", "ingest-status.json"), 64 << 20)
    if status is None:
        status = load(os.path.join(root, "banks", "ingest-status.json"), 64 << 20)
    report = status_report(status) if status is not None else journal_report(os.path.join(root, "banks", "failures.jsonl"))
    report["source"] = "ingest-status" if status is not None else "primary-journal"
    population = []
    for path in sorted(hits.get("provider-population-report.json", []))[:2]:
        value = load(path)
        block = value.get("provider_population") if isinstance(value, dict) else None
        if isinstance(block, dict):
            findings = block.get("findings")
            findings = findings if isinstance(findings, list) else []
            population.append((safe(block.get("status")), [safe(f.get("provider"), 64)
                               for f in findings[:12] if isinstance(f, dict)]))
    report["population"] = population
    return report, status


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    data = args[0] if args else "/srv/ar-local/data"
    days = max(1, min(60, int(args[1]))) if len(args) > 1 else 14
    runs = os.path.join(data, "runs")
    DENIED.clear()
    try:
        dates = sorted(d for d in os.listdir(runs) if re.fullmatch(r"20\d\d-\d\d-\d\d", d))[-days:]
    except OSError as error:
        print("RUNS_UNREADABLE", safe(type(error).__name__))
        return 3
    by_provider = collections.defaultdict(dict)
    unknown = False
    for day in dates:
        report, status = day_report(os.path.join(runs, day))
        unknown |= report["total"] is None
        print("DAY", day, "failure_rows=%s" % (report["total"] if report["total"] is not None else "UNKNOWN"),
              "reported_total=%s" % report["reported_total"],
              "providers=%d" % sum(v > 0 for v in report["providers"].values()),
              "population=%s" % json.dumps(report["population"]), "source=%s" % report["source"],
              "request_sample=%d" % sum(report["samples"].values()),
              "sample_complete=%s" % report["sample_complete"], "CAPPED" if report["capped"] else "")
        if day == dates[-1]:
            print("STATUS_SHAPE", json.dumps(shape(status)))
            print("FAILURE_AGGREGATES", json.dumps(report["aggregates"])[:8000])
        names = set(report["providers"]) | {key[0] for key in report["samples"]}
        for name in sorted(names)[:MAX_PROVIDERS]:
            number = report["providers"].get(name)
            if number == 0:
                continue
            sample = ["%s/%s/%s x%d" % (*key[1:], n) for key, n in report["samples"].items() if key[0] == name][:16]
            by_provider[name][day] = (number, report["categories"].get(name, {}), sample)
    print("PROVIDER_TABLE days=%d" % len(dates))
    for name, history in sorted(by_provider.items(), key=lambda item: -len(item[1]))[:MAX_PROVIDERS]:
        last = max(history)
        number, categories, sample = history[last]
        print(" ", name, "days=%d last=%s failures=%s" % (len(history), last, number if number is not None else "UNKNOWN"),
              "categories=" + json.dumps(categories)[:1200], "request_sample=" + "; ".join(sample)[:2000])
    for pointer in ("latest-observation.json", "latest-complete.json"):
        value = load(os.path.join(data, "state", "observation-pointers-v2", pointer))
        print("POINTER", pointer, json.dumps({k: safe(value[k]) for k in
              ("generation_id", "run_date", "state") if k in value}) if isinstance(value, dict) else "absent")
    if DENIED:
        print("PERMISSION_OR_READ_ERRORS", len(DENIED), type(DENIED[0]).__name__)
        return 3
    return 2 if unknown or not dates else 0


if __name__ == "__main__":
    raise SystemExit(main())
