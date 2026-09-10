"""Bind a frozen successful backup to explicit current configuration expectations."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--snapshot', type=Path, required=True)
parser.add_argument('--config', type=Path, required=True)
parser.add_argument('--config-sha256', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output = args.output.resolve()
raw_config = args.config.read_bytes()
assert hashlib.sha256(raw_config).hexdigest() == args.config_sha256
config = json.loads(raw_config)
root = args.snapshot / 'backup'
pointer = json.loads((root / 'catalog/latest-scheduled.json').read_bytes())
scheduled = json.loads((root / pointer['record_path']).read_bytes())
assert pointer['result'] == scheduled['result'] == 'PASS'
inventory = scheduled['detail'].get('after', scheduled['detail'])
components = {}
for kind in ('observation', 'control', 'macro'):
    relative = Path(inventory[kind]['receipt_path']).relative_to(Path(config['target'])).as_posix()
    components[kind] = {'path': relative, 'sha256': hashlib.sha256((root / relative).read_bytes()).hexdigest()}
expected = {'schema':'ARL-RECOVERY-RECEIPT-BINDING-V1',
    'production_sha':config['protected_sha'], 'receiver_sha':config['candidate_sha'],
    'operator':config['operator_sid'], 'observation_date':'2026-09-11',
    'recorded_backup_root':config['target'],
    'scheduled':{'path':pointer['record_path'], 'sha256':pointer['record_sha256']},
    'catalog_sha256':hashlib.sha256((root / 'catalog/generations.jsonl').read_bytes()).hexdigest(),
    'components':components}
args.output.mkdir(exist_ok=False)
expectation_path = args.output / 'expectations.json'
with expectation_path.open('xb') as output:
    output.write((json.dumps(expected,indent=2)+'\n').encode())
command = [config['python_path'], '-B', str(Path(config['receiver']) / 'laptop_recovery_receipts.py'),
    '--target',str(root),'--expectations',str(expectation_path),'--expectations-sha256',
    hashlib.sha256(expectation_path.read_bytes()).hexdigest(),'--snapshot']
env = {k:v for k,v in os.environ.items() if not k.upper().startswith(('PYTHON','GIT_'))}
result = subprocess.run(command,capture_output=True,text=True,timeout=120,env=env)
report = {'exact_command':command, 'exit_code':result.returncode,
          'stdout':result.stdout,'stderr':result.stderr,
          'verifier_sha256':hashlib.sha256(Path(command[2]).read_bytes()).hexdigest()}
(args.output / 'receipt-binding.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report))
raise SystemExit(result.returncode)
