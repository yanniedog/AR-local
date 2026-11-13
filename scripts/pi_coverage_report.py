"""Read-only coverage report run on the Pi: per-provider failures by day.

Reads retained run evidence only; writes nothing. Output is bounded and carries
provider names, phases, failure categories and HTTP statuses, never response
bodies, URLs with queries, or credentials.
"""
import collections
import json
import os
import sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "/srv/ar-local/data"
DAYS = max(1, min(60, int(sys.argv[2]))) if len(sys.argv) > 2 else 14
runs = os.path.join(DATA, "runs")


def load(path, limit=4 << 20):
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as handle:
            return json.loads(handle.read())
    except (OSError, ValueError):
        return None


DENIED = []


def find(root, names, depth=4):
    hits = {}
    base = root.rstrip("/").count("/")
    for cur, dirs, files in os.walk(root, onerror=DENIED.append):
        if cur.count("/") - base >= depth:
            dirs[:] = []
        for name in files:
            if name in names:
                hits.setdefault(name, []).append(os.path.join(cur, name))
    return hits


def status_failures(node, out, depth=0):
    """Collect provider failure rows from the retained ingest-status summary."""
    if depth > 6:
        return
    if isinstance(node, dict):
        name = node.get("bank") or node.get("provider") or node.get("brand")
        reason = node.get("failure_category") or node.get("category") or node.get("error_class") or node.get("reason")
        if isinstance(name, str) and (reason or node.get("phase")):
            out[(name[:48], str(node.get("phase"))[:24], str(reason)[:28], str(node.get("status"))[:6])] += 1
        for value in node.values():
            status_failures(value, out, depth + 1)
    elif isinstance(node, list):
        for value in node[:20000]:
            status_failures(value, out, depth + 1)


def shape(node):
    if isinstance(node, dict):
        return {str(k)[:40]: (v if isinstance(v, (int, float, bool, type(None))) else
                              (v[:60] if isinstance(v, str) and "://" not in v else type(v).__name__ +
                               ("[%d]" % len(v) if isinstance(v, (list, dict)) else "")))
                for k, v in list(node.items())[:60]}
    return type(node).__name__


try:
    dates = sorted(d for d in os.listdir(runs) if d[:2] == "20")[-DAYS:]
except OSError as error:
    print("RUNS_UNREADABLE", error)
    sys.exit(3)
by_provider = collections.defaultdict(dict)
for day in dates:
    root = os.path.join(runs, day)
    hits = find(root, {"failures.jsonl", "provider-population-report.json", "contract-lock.json"})
    rows = collections.Counter()
    capped = False
    status = load(os.path.join(root, "_exports", "ingest-status.json"), 64 << 20)
    if status is not None:
        status_failures(status, rows)
        if day == dates[-1]:
            print("STATUS_SHAPE", json.dumps(shape(status))[:3000])
    primary = os.path.join(root, "banks", "failures.jsonl")
    journals = sorted(hits.get("failures.jsonl", []), key=lambda path: (path != primary, path))
    capped = capped or len(journals) > 6
    for path in ([] if rows else journals[:6]):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index > 5000:
                        capped = True
                        break
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(row, dict):
                        continue
                    key = (str(row.get("bank") or row.get("provider"))[:48], str(row.get("phase"))[:24],
                           str(row.get("failure_category") or row.get("category"))[:28], str(row.get("status"))[:6])
                    rows[key] += 1
        except OSError as error:
            DENIED.append(error)
    population = []
    for path in hits.get("provider-population-report.json", [])[:2]:
        report = load(path)
        block = report.get("provider_population") if isinstance(report, dict) else None
        if not isinstance(block, dict):
            continue
        population.append((block.get("status"), [str(f.get("provider"))[:48] for f in (block.get("findings") or [])
                                                 if isinstance(f, dict)][:12]))
    exports = os.path.join(root, "_exports")
    listing = sorted(os.listdir(exports))[:60] if os.path.isdir(exports) else None
    print("DAY", day, "failure_rows=%d" % sum(rows.values()), "providers=%d" % len({k[0] for k in rows}),
          "population=%s" % json.dumps(population), "exports=%s" % (len(listing) if listing is not None else "absent"),
          "source=%s" % ("ingest-status" if status is not None else "journal"), "CAPPED" if capped else "")
    for key, count in rows.items():
        by_provider[key[0]].setdefault(day, []).append("%s/%s/%s x%d" % (key[1], key[2], key[3], count))
    if day == dates[-1] and listing:
        print("EXPORT_FILES", " ".join(listing))
print("PROVIDER_TABLE days=%d" % len(dates))
for name, days in sorted(by_provider.items(), key=lambda item: -len(item[1])):
    last = max(days)
    print("  %-48s days=%2d last=%s %s" % (name, len(days), last, "; ".join(days[last])[:160]))
for pointer in ("latest-observation.json", "latest-complete.json"):
    value = load(os.path.join(DATA, "state", "observation-pointers-v2", pointer))
    print("POINTER", pointer, json.dumps(value)[:400] if value is not None else "absent")
if DENIED:
    print("PERMISSION_OR_READ_ERRORS", len(DENIED), str(DENIED[0])[:160])
    sys.exit(3)
