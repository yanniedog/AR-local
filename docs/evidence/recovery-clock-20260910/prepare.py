"""Create immutable exact-candidate activation inputs; does not change a task."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

EVIDENCE = Path(__file__).resolve().parent
ROOT = Path(r'C:\code\backups\AR-local-user-session\recovery-clock-20260910-v7')
SOURCE = ROOT / 'source'
OLD = Path(r'C:\code\backups\AR-local-user-session\private-tools-20260910-v5\user-session-backup.json')
OLD_SHA = 'b5226e34e367393f9087b92c63dc6f6bd92054d7df2b24c88c45a793e529a9ff'
parser = argparse.ArgumentParser()
parser.add_argument('--commit', required=True)
COMMIT = parser.parse_args().commit
assert len(COMMIT) == 40 and all(c in '0123456789abcdef' for c in COMMIT)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create(path, value):
    with path.open('xb') as output:
        output.write((json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
    return sha(path)


assert sha(OLD) == OLD_SHA
old = json.loads(OLD.read_bytes())
pointer_path = Path(old['target']) / 'catalog/latest-scheduled.json'
pointer = json.loads(pointer_path.read_bytes())
assert pointer['result'] == 'PASS'
assert pointer['record_sha256'] == '3b76be3477997900aaeeefb253e1a76323c0f3d18214cbfa891d4062223581b7'
config = dict(old, receiver=str(SOURCE), candidate_sha=COMMIT,
              previous_runtime={'production_sha': old['protected_sha'], 'receiver_sha': old['candidate_sha'],
                                'record_sha256': pointer['record_sha256']})
tools = Path(r'C:\code\backups\AR-local-user-session\tools')
config['git_path'] = str(tools / 'mingit-2.55.0.5/cmd/git.exe')
config['git_sha256'] = sha(Path(config['git_path']))
for name in ('ssh', 'scp'):
    path = tools / 'git-ssh-2.55.0.5/usr/bin' / (name + '.exe')
    config['transport'][name + '_path'] = str(path)
    config['transport'][name + '_sha256'] = sha(path)
config['transport']['ssh_null_device'] = '/dev/null'
config_path = ROOT / 'user-session-backup.json'
config_sha = create(config_path, config)
contract = {'archive': str(tools / 'MinGit-2.55.0.5-64-bit.zip'),
            'package_sha256': '56d7b226b7693196cfc71fef26568f536c4a021ab6c37ff2db4287bed908e96e',
            'package_root': str(tools / 'mingit-2.55.0.5'),
            'ssh_archive': str(tools / 'git-ssh-2.55.0.5-verified.zip'),
            'ssh_sha256': 'd508c38435872da388545fc9d221fb4581c938a3030a081efb1d9576d9b928f8',
            'ssh_root': str(tools / 'git-ssh-2.55.0.5')}
contract_path = ROOT / 'tool-contract.json'
contract_sha = create(contract_path, contract)
deployment = dict(contract, schema='ARL-PRIVATE-GIT-V1', operator_sid=config['operator_sid'],
    decision_id='D-026-RECOVERY-CLOCK-20260910', candidate_sha=COMMIT,
    old_config=str(OLD), old_sha256=OLD_SHA, new_config=str(config_path), new_sha256=config_sha,
    tool_contract=str(contract_path), tool_contract_sha256=contract_sha,
    python_path=config['python_path'], python_sha256=config['python_sha256'],
    wrapper_sha256=sha(SOURCE / 'laptop_backup_private_git.ps1'),
    verifier_path=str(SOURCE / 'laptop_backup_git_dependency.py'),
    verifier_sha256=sha(SOURCE / 'laptop_backup_git_dependency.py'),
    launcher_path=str(SOURCE / 'run_laptop_backup_user_session.ps1'),
    launcher_sha256=sha(SOURCE / 'run_laptop_backup_user_session.ps1'),
    transition_helper_sha256=sha(SOURCE / 'laptop_backup_user_update.ps1'))
deployment_path = ROOT / 'private-tools-deployment.json'
deployment_sha = create(deployment_path, deployment)
now = datetime.now(timezone.utc)
decision = dict(id=deployment['decision_id'], result='NOT_STARTED',
    created_at_utc=now.isoformat(), created_at_hobart=now.astimezone(timezone(timedelta(hours=10))).isoformat(),
    author='Codex for jkoka', operator=config['operator_sid'], elevated=False,
    reason='The v5 manual run restored all three archives but its aggregate result failed because cdr-recovery-status.json changed only checked_at. Install the reviewed receiver that retains every recovery fact and raw archive bytes while excluding only that observation timestamp from control freshness, then verify the new exact pair now. D024 stopped before task mutation because its predecessor was failed. D025 used the original control API and unchanged scheduled check to obtain a real successful predecessor. Preserve all failed proposals, the original terminal and verified archives.',
    authorization='User explicitly requested completion, no Windows Yes/UAC prompts, and: Do it now rather than 6am.',
    plan_document_id='ARL-OPS-001', plan_version='1.5',
    plan_document_commit='9094a8e115958fcaf2cb36525736bd5e297e6b04',
    plan_controlled_sha256='a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada',
    plan_raw_sha256=sha(SOURCE / 'docs/PI_INGEST_PAYLOAD_RECOVERY_RUNBOOK.md'),
    candidate_sha=COMMIT, production_sha=config['protected_sha'],
    previous_config={'path': str(OLD), 'sha256': OLD_SHA},
    config={'path': str(config_path), 'sha256': config_sha},
    tool_contract={'path': str(contract_path), 'sha256': contract_sha},
    deployment={'path': str(deployment_path), 'sha256': deployment_sha},
    predecessor_record_sha256=pointer['record_sha256'],
    deviations=[{'change':'Normalized recovery-status observation timestamp in control revision',
                 'risk':'Ignoring a substantive recovery-state change',
                 'controls':'Preserve every status field except checked_at in semantic identity, retain and verify raw file bytes, verify normalized facts against restored file; unchanged strict private tools and all other freshness gates'},
                {'change':'Immediate manual verification after exact corrected receiver activation',
                 'risk':'Overlap and invalid natural-trigger inference',
                 'controls':'Ready task, existing locks and all original freshness/capacity/ingest gates; record manual origin and preserve natural failure'}],
    acceptance=['Exact merged PR670 Linux/Windows CI and substantive feedback disposition',
                'Full private-package and predecessor lineage validation before action mutation',
                'Existing ordinary-user transaction preserves task principal/triggers/settings and verifies action readback',
                'Probe succeeds, then original backup/restore/preflight/catalog checks; strict SSH exits remain enforced',
                'No A3 natural-trigger or A4 physical acceptance inferred from manual backup'],
    stop_conditions=['Any code/config/task/package/trust identity drift, busy lock/task or active ingest',
                     'No manual start at or after14:00 Hobart; original six-hour run bound and22:00 cutoff remain',
                     'Any Windows elevation/authentication prompt: stop without escalation'],
    rollback='Existing action-only transaction restores exported old action on failure. The old v5 action is known to report a false stale result when the monitor timestamp changes; rollback does not claim healthy unattended backups. Preserve all logs/configs/catalogs and failed alternatives.',
    exact_commands={'verify': [config['python_path'], '-B', str(SOURCE / 'laptop_backup_user_update.py'),
        '--old-config', str(OLD), '--old-sha256', OLD_SHA, '--config', str(config_path),
        '--config-sha256', config_sha, '--tool-contract', str(contract_path), '--tool-contract-sha256', contract_sha],
        'probe': ['powershell.exe', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-File',
            str(SOURCE / 'laptop_backup_private_git.ps1'), '-DeploymentPath', str(deployment_path),
            '-DeploymentSha256', deployment_sha, '-Mode', 'probe'],
        'manual_start': ['Start-ScheduledTask', '-TaskName', 'AR-local user-session backup']})
decision_sha = create(ROOT / 'D-026-activation-intent.json', decision)
for file in (config_path, contract_path, deployment_path, ROOT / 'D-026-activation-intent.json'):
    with (EVIDENCE / file.name).open('xb') as output:
        output.write(file.read_bytes())
print(json.dumps({'config_sha256': config_sha, 'deployment_sha256': deployment_sha,
                  'tool_contract_sha256': contract_sha, 'decision_sha256': decision_sha,
                  'candidate_sha': COMMIT, 'task_changed': False}))
