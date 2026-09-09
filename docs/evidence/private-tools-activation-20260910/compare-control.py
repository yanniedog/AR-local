"""Read-only comparison of retained control data against the Pi's current files."""
import hashlib
import json
import runpy
import subprocess
from datetime import datetime, timezone
from pathlib import Path

output = Path(__file__).parent
config = json.loads((output / 'user-session-backup.json').read_bytes())
reader = Path(config['receiver']) / 'laptop_recovery_runtime.py'
assert hashlib.sha256(reader.read_bytes()).hexdigest() == '6b6e102bc867ef76802acb36a00e22e00d4c569fa8ffab3f091850d5703785bd'
runtime = runpy.run_path(str(reader))
receipt_path = Path(config['target']) / 'control/20260909T232759Z-5d52f0e69ec41a2b/receipt.json'
receipt = json.loads(receipt_path.read_bytes())
manifest_raw = receipt_path.with_name('source-manifest.json').read_bytes()
assert hashlib.sha256(manifest_raw).hexdigest() == receipt['source_manifest_sha256']
files = [f for f in json.loads(manifest_raw)['files'] if f['path'].startswith('data/')]
remote = '''
import hashlib,json
from pathlib import Path
files=FILES
root=Path('/srv/ar-local/data')
changes=[]
expected=set()
for item in files:
 relative=item['path'][5:]
 path=root/relative
 assert path.resolve().is_relative_to(root) and not path.is_symlink()
 expected.add(relative)
 if not path.is_file():
  changes.append({'path':item['path'],'change':'missing'});continue
 sha=hashlib.sha256()
 with path.open('rb') as stream:
  for block in iter(lambda:stream.read(4*1024**2),b''):sha.update(block)
 if sha.hexdigest()!=item['sha256']:
  changes.append({'path':item['path'],'before':item['sha256'],'after':sha.hexdigest()})
actual=set()
for folder in ('state','predeploy','runs-archive'):
 for path in (root/folder).rglob('*'):
  if path.is_file() and not path.is_symlink():
   if folder=='state' and (path.name.endswith(('.lock','.tmp','.partial')) or '.partial-' in path.name):continue
   actual.add(path.relative_to(root).as_posix())
print(json.dumps({'changed':changes,'added':sorted(actual-expected),'files_checked':len(files)}))
'''.replace('FILES',repr(files),1)
command = runtime['ssh_prefix'](config) + ['/usr/bin/python3','-I','-S','-B','-']
result = subprocess.run(command,input=remote,capture_output=True,text=True,timeout=90)
report={'at_utc':datetime.now(timezone.utc).isoformat(),'exit_code':result.returncode,
        'exact_command':command,'remote_source_sha256':hashlib.sha256(remote.encode()).hexdigest(),
        'stdout':result.stdout,'stderr':result.stderr,'read_only':True}
with (output / 'control-difference.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
print(json.dumps(report))
raise SystemExit(result.returncode)
