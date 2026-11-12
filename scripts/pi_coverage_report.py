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
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 14
runs = os.path.join(DATA, "runs")


def load(path, limit=4 << 20):
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as handle:
            return json.loads(handle.read())
    except (OSError, ValueError):
        return None


def find(root, names, depth=4):
    hits = {}
    base = root.rstrip("/").count("/")
    for cur, dirs, files in os.walk(root):
        if cur.count("/") - base >= depth:
            dirs[:] = []
        for name in files:
            if name in names:
                hits.setdefault(name, []).append(os.path.join(cur, name))
    return hits


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
    for path in hits.get("failures.jsonl", [])[:6]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index > 5000:
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
            print(day, "FAILURES_UNREADABLE", error)
    population = []
    for path in hits.get("provider-population-report.json", [])[:2]:
        report = load(path) or {}
        block = report.get("provider_population") or {}
        population.append((block.get("status"), [str(f.get("provider"))[:48] for f in (block.get("findings") or [])
                                                 if isinstance(f, dict)][:12]))
    exports = os.path.join(root, "_exports")
    listing = sorted(os.listdir(exports))[:60] if os.path.isdir(exports) else None
    print("DAY", day, "failure_rows=%d" % sum(rows.values()), "providers=%d" % len({k[0] for k in rows}),
          "population=%s" % json.dumps(population), "exports=%s" % (len(listing) if listing is not None else "absent"))
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
