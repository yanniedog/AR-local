"""Append the observed activation terminal state, preserving the old ledger bytes."""
import hashlib
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent
handoff = ROOT / 'docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
original = handoff.read_bytes()
entry = json.loads(re.findall(r'```json\s*(.*?)\s*```', original.decode(), re.S)[-1])
assert entry['entry_id'] == 'HANDOFF-20260910-PRIVATE-TOOLS-PREPARED'
decision = json.loads((EVIDENCE / 'D-023-activation-intent.json').read_bytes())
config = json.loads((EVIDENCE / 'user-session-backup.json').read_bytes())
terminal = json.loads((EVIDENCE / 'terminal-summary.json').read_bytes())
now = datetime.now(timezone.utc)
entry.update(previous_entry_id=entry['entry_id'],
    entry_id='HANDOFF-20260910-PRIVATE-TOOLS-ACTIVATED',
    created_at_utc=now.isoformat(), created_at_hobart=now.astimezone(timezone(timedelta(hours=10))).isoformat(),
    result='RUNNING', scope='Private-tool activation and immediate manual backup terminal; A3/A4 remain open',
    candidate_code_sha=config['candidate_sha'], receiver_path=config['receiver'],
    receiver_config_sha256=decision['config']['sha256'],
    plan_raw_sha256=decision['plan_raw_sha256'],
    current_phase='A3: installed private tools; actual manual backup outcome recorded',
    historical_backup_result=entry['backup_result'], backup_result=terminal['backup'],
    task=terminal['task'], selected_generation=terminal.get('selected_generation'),
    deviations=decision['deviations'],
    deviation_decision={'id': decision['id'], 'intent': 'docs/evidence/private-tools-activation-20260910/D-023-activation-intent.json',
                        'created_before_activation': True, 'terminal': terminal['guard'],
                        'scope': 'Outer activation and manual-start transaction; receiver component checks unchanged'},
    snapshot_notice='The v5 receiver/config is installed. Earlier v1-v4 private-tool proposals were not installed. September9 backup details are historical and retain D022 limitations.',
    next_action='Complete PR669 gates/feedback. Preserve the installed pair for genuine natural-trigger evidence; inspect only after terminal completion. Continue physical preparation without media mutation. Do not repeat this completed manual backup.',
    reason='System tool drift caused the natural06:00 failure. Authenticated private tools are now installed and the requested manual run was actually executed.')
entry['independent_states'].update(
    dashboard='PASS:09:13 live Pi browser shows September10 and7260 mortgage rows, no warn/error logs; verify:local passed. No deployment/restart.',
    backup=terminal['backup'],
    current_day='September10 publication, live dashboard and actual manual backup results independently recorded.',
    capture='See actual component archive/check identities in terminal-summary.json; no inference from public publication alone.')
entry['completed_gates'].extend([
    'PR668 merged d930716ae1d32c19dd73b95ea5d719f6209eb179; Linux/Windows CI and substantive feedback dispositions complete',
    'D023 intent before activation; authenticated predecessor chain and805 package files; action-only task transaction PASS with XML/readback',
    'Ordinary-user hidden probe PASS09:13:32; user-requested manual task actually started09:14:25',
    'Live Pi browser and verify:local PASS;46 focused dependency/handoff tests PASS'])
entry['open_gates'] = [x for x in entry['open_gates'] if not x.startswith(('Current private-tools', 'D-023 exact'))]
if terminal['backup']['result'] != 'PASS':
    entry['open_gates'].insert(0, 'Manual backup failed; inspect preserved terminal and repair only its actual cause before bounded recovery')
    entry['next_action'] = 'Complete PR669 CI/review for the demonstrated checked_at-only control false-stale fix. Record a new exact receiver/config/action decision before activation; retain all v5 archives and its failed aggregate receipt. Then finish actual current-pair backup verification without relaxing any substantive freshness or restore checks.'
binding = terminal['backup']['receipt_binding']
if not isinstance(binding, dict) or binding.get('receipt_binding') != 'PASS':
    entry['open_gates'].insert(0, 'Independent current receipt binding has not passed; inspect its preserved result')
entry['timing'].update(manual_start_hobart=terminal['task']['last_run'],
    earliest_natural_terminal_inspection_hobart='After September11 06:00 natural task is terminal; never acquire competing locks while Running')
entry['commands'].update(current_slice_workdir=str(ROOT),
    current_slice=['npm run pr:merge -- --pr 669', 'npm run pr:bot-feedback-audit'],
    activation=decision['exact_commands'],
    manual_backup='Executed once at09:14:25 September10 after create-new manual-start-intent.json; do not replay',
    current_evidence=terminal['commands'])
entry['repository_state']['correction'] = {'path': str(ROOT), 'branch': 'agent/private-tools-closeout-0910',
    'base_sha': config['candidate_sha'], 'clean_at_start': True,
    'scope_of_changes': 'Auxiliary null-device compatibility fix and actual activation/manual-backup evidence'}
entry['repository_state']['installed_receiver'] = {'path':config['receiver'],'sha':config['candidate_sha'],
    'clean_at_snapshot':True,'checked_at_hobart':'2026-09-10T09:13:32+10:00',
    'current_cleanliness':'Whole-package and exact clean-source verification passed before guarded probe/run'}
entry['repository_state']['production']['current_cleanliness'] = 'Read-only source verification and actual backup preflight; no production mutation'
entry['rollback_or_preservation']['current_slice'] = 'Action-only installation passed. Preserve exported old/new XML and original configurations; old system-tool action is known blocked by drift.'
entry['known_risks'] = [x for x in entry['known_risks'] if 'not installed' not in x]
entry['known_risks'].append('Private tools remove system Git/SSH update drift; this manual run cannot establish unattended natural-trigger or physical recovery acceptance.')
entry['unresolved_findings'] = [x for x in entry['unresolved_findings'] if x['id'] != 'natural-backup-20260910-tool-drift']
for item in entry['unresolved_findings']:
    if item['id'] == 'installed-transport-reliability':
        item['issue'] = 'Private tools installed and actual manual outcome captured; unattended natural-trigger reliability remains to be observed.'
if terminal['backup']['result'] != 'PASS':
    entry['unresolved_findings'].append({'id':'manual-backup-20260910','status':'OPEN',
        'issue':'All three component restores passed; aggregate FAIL because cdr-recovery-status.json changed only checked_at. PR669 source fix retains all recovery facts and raw archive bytes; exact activation and current-pair verification remain.'})
for path in sorted(EVIDENCE.rglob('*')):
    if path.is_file() and path.name != 'pr-body.txt':
        raw = path.read_bytes()
        entry['evidence_artifacts'].append({'path':path.relative_to(ROOT).as_posix(),
            'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
for item in entry['evidence_artifacts']:
    raw = (subprocess.run(['git','show','HEAD:' + item['path']],cwd=ROOT,capture_output=True,check=True).stdout
           if item.get('byte_scope','').startswith('Checked-in Git blob')
           else (ROOT / item['path']).read_bytes())
    assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256'], item['path']
suffix = ('\n\n## Entry `' + entry['entry_id'] + '`\n\n```json\n' + json.dumps(entry,indent=2) + '\n```\n').encode()
handoff.write_bytes(original + suffix)
assert handoff.read_bytes().startswith(original)
print(json.dumps({'entry':entry['entry_id'],'evidence_files':len(entry['evidence_artifacts']),
                  'preserved_prefix_bytes':len(original)}))
