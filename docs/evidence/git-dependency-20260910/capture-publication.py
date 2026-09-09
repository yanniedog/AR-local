"""Current-day public rate checks; no producer or device mutation."""
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
BASE = 'https://github.com/yanniedog/AR-local/releases/download/'


def fetch(url):
    with urlopen(Request(url, headers={'Cache-Control': 'no-cache'}), timeout=30) as response:
        return response.read()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


checks = []
for tag, name in [('app-payload-latest', 'manifest.json'),
                  ('app-payload-latest', 'manifest-v2.json'),
                  ('app-payload-latest', 'dates-index.json'),
                  ('app-payload-2026-09-10', 'manifest.json')]:
    url = BASE + tag + '/' + name
    raw = fetch(url)
    item = json.loads(raw)
    with (ROOT / (tag + '-' + name)).open('xb') as output:
        output.write(raw)
    row = {'url': url, 'bytes': len(raw), 'sha256': sha(raw),
           'date': item.get('run_date', item.get('latest_date'))}
    assert row['date'] == '2026-09-10', row
    if name == 'manifest.json':
        descriptor = item['files']['core']
        core_raw = fetch(descriptor['url'])
        assert sha(core_raw) == descriptor['sha256'] and len(core_raw) == descriptor['bytes']
        core = json.loads(gzip.decompress(core_raw))
        row.update(core_sha256=sha(core_raw), core_date=core.get('run_date'),
                   core_keys=list(core), generated_at=item['generated_at'])
        row['section_structure'] = {key: len(value) if isinstance(value, (list, dict)) else type(value).__name__
                                    for key, value in core.items()}
        assert core.get('run_date') == '2026-09-10'
    checks.append(row)
result = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'result': 'PASS',
          'checks': checks, 'device': 'UNVERIFIED: displayed screen/date/error requested'}
with (ROOT / 'publication-check.json').open('x', encoding='utf-8') as output:
    json.dump(result, output, indent=2)
print(json.dumps(result))
