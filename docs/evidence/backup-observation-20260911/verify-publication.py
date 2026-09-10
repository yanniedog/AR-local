"""Download and verify the September 11 public payload without publishing."""
import gzip
import hashlib
import io
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).parent / 'publication'
ROOT.mkdir(exist_ok=False)
BASE = 'https://github.com/yanniedog/AR-local/releases/download/app-payload-latest/'
DAY = '2026-09-11'

def fetch(url):
    assert url.startswith(BASE)
    with urlopen(url, timeout=30) as response:
        value = response.read(128 * 1024**2 + 1)
    assert len(value) <= 128 * 1024**2
    return value

raw = {name: fetch(BASE + name) for name in ('manifest.json', 'manifest-v2.json', 'dates-index.json')}
v1, v2, index = [json.loads(raw[n]) for n in ('manifest.json', 'manifest-v2.json', 'dates-index.json')]
assert v1['run_date'] == v2['run_date'] == index['latest_date'] == DAY
assert DAY in index['dates']
assert v2['base']['core_sha'] == v1['files']['core']['sha256']
assert v2['base']['details_sha'] == v1['files']['details']['sha256']
checks = []
for version, manifest in (('v1', v1), ('v2', v2)):
    for name, descriptor in manifest['files'].items():
        compressed = fetch(descriptor['url'])
        digest = hashlib.sha256(compressed).hexdigest()
        assert len(compressed) == descriptor['bytes'] and digest == descriptor['sha256']
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as archive:
            decoded = archive.read(256 * 1024**2 + 1)
        assert len(decoded) <= 256 * 1024**2
        value = json.loads(decoded)
        if version == 'v2':
            assert descriptor['encoding'] == 'gzip' and len(decoded) == descriptor['uncompressed_bytes']
        if name in ('core', 'details', 'product_history'):
            assert value['run_date'] == DAY
        if name == 'product_history':
            assert value['core_sha'] == v2['base']['core_sha']
        if name == 'economic_outlook':
            assert value['kind'] == 'observed_economic_indicators'
            assert value['generated_at'] == v2['generated_at']
            dt = datetime.fromisoformat(value['generated_at'].replace('Z', '+00:00'))
            assert dt.astimezone(timezone(timedelta(hours=10))).date().isoformat() == DAY
        (ROOT / (version + '-' + name + '.json.gz')).write_bytes(compressed)
        checks.append({'version':version, 'asset':name, 'sha256':digest,
            'bytes':len(compressed), 'decoded_bytes':len(decoded), 'result':'PASS'})
for name, value in raw.items():
    assert fetch(BASE + name) == value
    (ROOT / name).write_bytes(value)
report = {'checked_at_utc':datetime.now(timezone.utc).isoformat(), 'result':'PASS',
    'run_date':DAY, 'exact_command':[sys.executable, str(Path(__file__).resolve())],
    'manifest_sha256':{n:hashlib.sha256(v).hexdigest() for n,v in raw.items()}, 'checks':checks,
    'scope':'All rolling v1/v2 descriptors verified for size/hash/gzip/JSON; core/details/product history and economic outlook dates checked; current dates index. Device state and dated release not verified by this script.'}
(ROOT / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report))
