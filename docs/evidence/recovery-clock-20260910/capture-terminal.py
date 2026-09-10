"""Freeze this activation's terminal evidence; never start or alter a task."""
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def task_state():
    command = ("$t=Get-ScheduledTask -TaskName 'AR-local user-session backup';"
               "$i=Get-ScheduledTaskInfo -TaskName $t.TaskName;"
               "[ordered]@{state=[string]$t.State;last_run=$i.LastRunTime.ToString('o');"
               "last_result=$i.LastTaskResult;next_run=$i.NextRunTime.ToString('o');"
               "action=$t.Actions[0].Arguments;execute=$t.Actions[0].Execute;"
               "working_directory=$t.Actions[0].WorkingDirectory;"
               "run_level=[string]$t.Principal.RunLevel}|ConvertTo-Json -Compress")
    output = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, check=True, timeout=30)
    state = json.loads(output.stdout)
    if state['state'] != 'Ready' or state['run_level'] != 'Limited':
        raise ValueError('task must be terminal and ordinary-user before capture')
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deployment-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before = task_state()
    root = args.deployment_root
    config = json.loads((root / 'user-session-backup.json').read_bytes())
    target = Path(config['target'])
    decision = json.loads((root / 'D-026-activation-intent.json').read_bytes())
    if digest((root / 'user-session-backup.json').read_bytes()) != decision['config']['sha256']:
        raise ValueError('config differs from the pre-action decision')
    if digest((root / 'private-tools-deployment.json').read_bytes()) != decision['deployment']['sha256']:
        raise ValueError('deployment differs from the pre-action decision')
    if before['working_directory'] != config['receiver'] or decision['deployment']['sha256'] not in before['action']:
        raise ValueError('task action is not the captured deployment')
    files = {}
    for name in ('manual-start-intent.json', 'activation-probe.stdout', 'activation-probe.stderr'):
        files['activation/' + name] = root / name
    for folder in ('task-update', 'guard-executions', 'logs'):
        for path in (root / folder).rglob('*'):
            if path.is_file():
                files['activation/' + path.relative_to(root).as_posix()] = path
    for pattern in ('catalog/*.json', 'catalog/*.jsonl', 'catalog/scheduled-runs/*.json',
                    'observations/*/*/receipt.json', 'macro/*/receipt.json',
                    'control/*/receipt.json', 'user-session-executions/*.json'):
        for path in target.glob(pattern):
            files['backup/' + path.relative_to(target).as_posix()] = path
            if path.name == 'receipt.json':
                receipt = json.loads(path.read_bytes())
                manifest = path.parent / 'source-manifest.json'
                if receipt.get('candidate_code_sha') == config['candidate_sha'] and manifest.is_file():
                    if digest(manifest.read_bytes()) != receipt['source_manifest_sha256']:
                        raise ValueError('current component manifest digest differs from receipt')
                    files['backup/' + manifest.relative_to(target).as_posix()] = manifest
    guards = [json.loads(p.read_bytes()) for p in (root / 'guard-executions').glob('*.json')]
    completed = [g for g in guards if g['mode'] == 'run']
    if len(completed) != 1:
        raise ValueError('require exactly one completed guarded run for this activation')
    if completed[0]['deployment_sha256'] != decision['deployment']['sha256']:
        raise ValueError('guard terminal is not bound to the activated deployment')
    payloads = {name: path.read_bytes() for name, path in files.items()}
    if before != task_state():
        raise ValueError('task changed during capture')
    if any(path.read_bytes() != payloads[name] for name, path in files.items()):
        raise ValueError('metadata changed during capture')
    args.output.mkdir(exist_ok=False)
    manifest = []
    for name, raw in sorted(payloads.items()):
        path = args.output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        manifest.append({'path': name, 'bytes': len(raw), 'sha256': digest(raw)})
    result = {'at_utc': datetime.now(timezone.utc).isoformat(), 'task': before,
              'decision': decision['id'], 'guard': completed[0],
              'origin': 'manual', 'natural_trigger': False, 'physical_recovery': 'BLOCKED',
              'scope': 'Frozen terminal metadata; independent receipt/archive checks separate',
              'files': manifest}
    (args.output / 'capture.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'path': str(args.output), 'files': len(manifest),
                      'task_result': before['last_result'], 'guard_result': completed[0]['result']}))


if __name__ == '__main__':
    main()
