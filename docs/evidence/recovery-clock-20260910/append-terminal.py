"""Append the full observed D026 terminal without rewriting prior evidence."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
E = Path(__file__).parent
path = ROOT / 'docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
old = path.read_bytes()
entry = json.loads(re.findall(rb'```json\s*(.*?)\s*```', old, re.S)[-1])
assert entry['entry_id'] == 'HANDOFF-20260910-RECOVERY-CLOCK-RUNNING'
summary = json.loads((E / 'terminal-summary.json').read_bytes())
assert summary['backup']['result'] == 'PASS'
assert summary['backup']['receipt_binding']['receipt_binding'] == 'PASS'
now = datetime.now(timezone.utc)
entry.update(previous_entry_id=entry['entry_id'], entry_id='HANDOFF-20260910-RECOVERY-CLOCK-VERIFIED',
    created_at_utc=now.isoformat(), created_at_hobart=now.astimezone(timezone(timedelta(hours=10))).isoformat(),
    result='PASS', scope='D026 manual operational backup, actual component restores and independent frozen receipt binding; A3/A4 remain open',
    current_phase='Corrected ordinary-user manual backup verified; preserve installed pair for natural-trigger proof',
    backup_result=summary['backup'], task=summary['task'], guard=summary['guard'],
    selected_generation=summary['selected_generation'], last_verified_generation=summary['selected_generation'],
    snapshot_notice='Terminal snapshot: native scheduled result PASS, guard PASS, task Ready/0, all three restores PASS. Earlier running and failed outcomes remain unchanged.',
    next_action='Close evidence PR671 through the reviewed guarded CLI. Preserve installed v7 receiver/configuration. Inspect the next genuine unchanged automatic trigger only after it is terminal, with fresh complete A3 controls and independent daily ingest/publication/dashboard checks. No physical actions before A3 and all A4 safeguards.')
entry['independent_states'].update(backup=summary['backup'],
    current_day='September10 public feeds and live dashboard verified at separately recorded times; D026 manual backup PASS10:09:51 and metadata binding PASS10:18:04. Device symptom remains unverified.')
entry['completed_gates'].extend([
    'D026 native scheduled execution PASS10:09:51; guard PASS and Task Scheduler Ready/exit0',
    'Actual observation/control/macro archives restored and verified, catalog sequences150/151/152; all current at terminal',
    'Frozen240-file metadata packet independently bound to current production/receiver/operator/date/catalog/component identities PASS10:18:04',
    'PR668 all nine substantive threads and PR669 all three late substantive threads individually disposed and resolved'])
entry['open_gates'] = [x for x in entry['open_gates'] if not x.startswith('D026 active')]
entry['open_gates'].insert(0, 'PR671 evidence-only guarded closeout and merged feedback audit')
entry['timing'].update(manual_completed_at=summary['backup']['completed_at'],
    natural_trigger_hobart='2026-09-11T06:00:00+10:00',
    earliest_natural_terminal_inspection_hobart='After September11 06:00 natural task is terminal; never classify the September10 manual run as natural proof')
entry['commands'].update(current_slice=['npm run pr:merge -- --pr 671', 'npm run pr:bot-feedback-audit'],
    manual_backup='Completed once under D026; no replay needed',
    current_evidence={'summary':'docs/evidence/recovery-clock-20260910/terminal-summary.json',
        'packet':summary['packet'], 'commands':summary['commands'],
        'capture':'python docs/evidence/recovery-clock-20260910/capture-terminal.py --deployment-root C:\\code\\backups\\AR-local-user-session\\recovery-clock-20260910-v7 --output C:\\code\\backups\\AR-local-user-session\\recovery-clock-20260910-v7\\terminal-snapshot'})
entry['repository_state']['correction']['pr'] = 'https://github.com/yanniedog/AR-local/pull/671'
entry['repository_state']['installed_receiver']['current_cleanliness'] = 'Exact clean-source/config and 805 private package files authenticated by the successful actual guarded run; installed pair preserved'
entry['unresolved_findings'] = [x for x in entry['unresolved_findings'] if x['id'] != 'D026-current-backup']
entry['acceptance_criteria']['manual_execution'] = 'D026 operational backup and original restore checks PASS; independent receipt binding PASS. Manual origin does not satisfy A3 natural-trigger or A4 physical acceptance. Historical September9 controlled BLOCKED remains unchanged.'
entry['revised_acceptance_criteria'] = dict(entry['acceptance_criteria'])
entry['known_risks'] = [x for x in entry['known_risks'] if not x.startswith(('A later source change', 'The September9 22:57'))]
entry['known_risks'].append('Actual recovery facts or source content may change after the dated terminal; fresh status is required before later dependent operations.')
existing = {item['path']: item for item in entry['evidence_artifacts']}
for artifact in sorted(E.rglob('*')):
    if not artifact.is_file():
        continue
    raw = artifact.read_bytes()
    item = {'path':artifact.relative_to(ROOT).as_posix(), 'bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}
    if item['path'] in existing:
        assert item == existing[item['path']], 'Previously recorded artifact changed: ' + item['path']
    else:
        entry['evidence_artifacts'].append(item)
suffix = ('\n\n## Entry `' + entry['entry_id'] + '`\n\n```json\n' + json.dumps(entry, indent=2) + '\n```\n').encode()
path.write_bytes(old + suffix)
assert path.read_bytes().startswith(old)
print(json.dumps({'entry':entry['entry_id'], 'evidence_files':len(entry['evidence_artifacts'])}))
