"""Package captured bytes and report actual outcomes without reclassifying them."""
import argparse
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--snapshot', type=Path, required=True)
args = parser.parse_args()
output = Path(__file__).parent
capture = json.loads((args.snapshot / 'capture.json').read_bytes())
root = args.snapshot / 'backup'
pointer = json.loads((root / 'catalog/latest-scheduled.json').read_bytes())
scheduled = json.loads((root / pointer['record_path']).read_bytes())
assert hashlib.sha256((root / pointer['record_path']).read_bytes()).hexdigest() == pointer['record_sha256']
guard = capture['guard']
config = json.loads((output / 'user-session-backup.json').read_bytes())
passed = (guard['result'] == scheduled['result'] == 'PASS' and capture['task']['last_result'] == 0
          and scheduled['candidate_code_sha'] == config['candidate_sha'])
binding_path = output / 'binding-current/receipt-binding.json'
binding = json.loads(binding_path.read_bytes()) if binding_path.exists() else None
binding_result = json.loads(binding['stdout']) if binding and binding['exit_code'] == 0 else None
assert binding_result and binding_result.get('receipt_binding') == 'PASS', 'Current frozen verification must pass before this combined report'
inventory = scheduled['detail'].get('after', scheduled['detail'])
components = {}
selected = None
catalog = [json.loads(line) for line in (root / 'catalog/generations.jsonl').read_bytes().splitlines()]
for kind in ('observation', 'control', 'macro'):
    current = inventory.get(kind, {})
    if current.get('receipt_path'):
        relative = Path(current['receipt_path']).relative_to(Path(config['target'])).as_posix()
    elif kind == 'control':
        relative = json.loads((root / 'catalog/latest-control.json').read_bytes())['receipt_path']
    else:
        continue
    raw = (root / relative).read_bytes()
    receipt = json.loads(raw)
    if receipt['candidate_code_sha'] != config['candidate_sha']:
        continue
    matched = [item for item in catalog if item['receipt_path'] == relative]
    assert len(matched) == 1
    components[kind] = {'path':relative,'sha256':hashlib.sha256(raw).hexdigest(),
        'archive_sha256':receipt['archive_sha256'],'archive_bytes':receipt['archive_bytes'],
        'source_bytes':receipt['source_bytes'],'completed_at':receipt['completed_at'],
        'catalog_sequence':matched[0]['sequence'],'checks':receipt['checks'],
        'restore_result':receipt['result'],'freshness':current.get('status')}
    if kind == 'observation':
        selected = receipt['checks']['observation']['latest_pointer']['generation_id']
packet = io.BytesIO()
with zipfile.ZipFile(packet,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for path in sorted(args.snapshot.rglob('*')):
        if path.is_file():
            archive.writestr(path.relative_to(args.snapshot).as_posix(),path.read_bytes())
raw_packet = packet.getvalue()
packet_sha = hashlib.sha256(raw_packet).hexdigest()
packet_path = output / ('terminal-metadata-' + packet_sha + '.zip')
with packet_path.open('xb') as destination:
    destination.write(raw_packet)
task = dict(capture['task'],name='AR-local user-session backup',
            action_changed=False,principal_triggers_settings_preserved=True,
            status_checked_at_utc=capture['at_utc'])
summary = {'task':task,'guard':guard,'selected_generation':selected,
    'backup':{'result':'PASS' if passed else 'FAIL','scheduled_result':scheduled['result'],
        'completed_at':scheduled['timestamps']['completed_at'],
        'terminal':{'path':pointer['record_path'],'sha256':pointer['record_sha256']},
        'catalog_entries':len((root / 'catalog/generations.jsonl').read_bytes().splitlines()),
        'catalog_sha256':hashlib.sha256((root / 'catalog/generations.jsonl').read_bytes()).hexdigest(),
        'components':components,'receipt_binding':binding_result or 'NOT_PASSED',
        'natural_trigger':'UNVERIFIED', 'observed_start':'06:00:01 Hobart; trigger attribution unavailable','physical_recovery':'BLOCKED',
        'decision':'Unchanged D026 deployment; September11 read-only terminal observation, not a new activation or manual start'},
    'packet':{'path':packet_path.name,'bytes':len(raw_packet),'sha256':packet_sha},
    'commands':{'freeze':[sys.executable,*sys.argv],
                'receipt_binding':binding['exact_command'] if binding else None},
    'scope':'Observed 06:00 operational backup and separate frozen receipt verification; natural trigger attribution UNVERIFIED and A4 BLOCKED'}
with (output / 'terminal-summary.json').open('x',encoding='utf-8') as destination:
    json.dump(summary,destination,indent=2)
    destination.write('\n')
print(json.dumps({'backup':summary['backup']['result'],'components':list(components),
                  'receipt_binding':binding_result,'packet':summary['packet']}))
