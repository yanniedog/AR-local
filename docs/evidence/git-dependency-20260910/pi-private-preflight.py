"""One bounded read-only SSH session; preserves strict remote exit validation."""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
reader = ROOT / 'laptop_recovery_runtime.py'
assert hashlib.sha256(reader.read_bytes()).hexdigest() == '6b6e102bc867ef76802acb36a00e22e00d4c569fa8ffab3f091850d5703785bd'
runtime = runpy.run_path(str(reader))
path = ROOT / 'docs/evidence/git-dependency-20260910/read-only-tool-proposal.json'
assert hashlib.sha256(path.read_bytes()).hexdigest() == '2df04d731f6fba90c1a30243e7bae96c1715cd50cbfdc85a13cd37195860c8b5'
config = json.loads(path.read_bytes())
prefix = runtime['ssh_prefix'](config)
remote = r'''
import json,subprocess,os,hashlib
from pathlib import Path
env={k:v for k,v in os.environ.items() if not k.upper().startswith(('GIT_','PYTHON'))}
env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL='/dev/null',GIT_OPTIONAL_LOCKS='0')
commands=[]
def run(args):
 r=subprocess.run(args,capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=20,env=env)
 commands.append({'args':args,'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
 if r.returncode: raise RuntimeError('read-only command failed: '+str(args))
 return r.stdout.strip()
p=['/usr/bin/git','--no-optional-locks','-c','core.fsmonitor=false','-c','core.untrackedCache=false','-C','/srv/ar-local/AR-local']
assert run(p+['rev-parse','--show-toplevel'])=='/srv/ar-local/AR-local'
assert run(p+['rev-parse','HEAD'])=='3de4d35d1f3af8b647477bfeb327c9466f5c49f6'
flags=run(p+['ls-files','-v','-z'])
assert all(x[0] not in 'Sabcdefghijklmnopqrstuvwxyz' for x in flags.split('\0') if x)
assert not run(p+['status','--porcelain=v1','--untracked-files=all','--ignore-submodules=none'])
run(['/usr/bin/systemctl','show','ar-local-daily.service','ar-local-ingest-now.service','ar-local-dashboard.service','--property=Id,ActiveState,SubState,Result,ExecMainStatus,ExecMainStartTimestamp,ExecMainExitTimestamp'])
run(['/usr/bin/systemctl','show','ar-local-daily.timer','--property=ActiveState,NextElapseUSecRealtime'])
state=Path('/srv/ar-local/data/state')
files=[]
for p in state.rglob('*2026-09-10*.json'):
 if p.is_file() and p.stat().st_size<100000:
  raw=p.read_bytes(); files.append({'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'value':json.loads(raw)})
print(json.dumps({'result':'PASS','commands':commands,'current_day_state_files':files}))
'''
started = datetime.now(timezone.utc)
result = subprocess.run(prefix + ['/usr/bin/python3', '-I', '-S', '-B', '-'],
                        input=remote, capture_output=True, text=True, timeout=90)
value = {'at_utc': started.isoformat(), 'exit': result.returncode,
         'exact_argv': prefix + ['/usr/bin/python3', '-I', '-S', '-B', '-'],
         'remote_source_sha256': hashlib.sha256(remote.encode()).hexdigest(),
         'stdout': result.stdout, 'stderr': result.stderr,
         'read_only': True, 'accepted': result.returncode == 0}
out = Path(__file__).parent / ('pi-private-preflight-' + started.strftime('%Y%m%dT%H%M%S') + '.json')
with out.open('x', encoding='utf-8') as stream:
    json.dump(value, stream, indent=2)
print(json.dumps({'path': str(out), 'exit': result.returncode, 'stderr': result.stderr,
                  'stdout_tail': result.stdout[-6500:]}))
raise SystemExit(result.returncode != 0)
