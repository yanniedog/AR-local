"""Append the full observed September 11 state without changing history."""
import hashlib
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

E = Path(__file__).parent
ROOT = Path(__file__).resolve().parents[3]
path = ROOT / 'docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
old = path.read_bytes()
entry = json.loads(re.findall(rb'```json\s*(.*?)\s*```', old, re.S)[-1])
assert entry['entry_id'] == 'HANDOFF-20260910-RECOVERY-CLOCK-VERIFIED'
summary = json.loads((E / 'terminal-summary.json').read_bytes())
task = json.loads((E / 'task-observation.json').read_text(encoding='utf-8-sig'))
publication = json.loads((E / 'publication/report.json').read_bytes())
assert summary['backup']['result'] == 'PASS'
assert summary['backup']['receipt_binding']['receipt_binding'] == 'PASS'
assert task['history_enabled'] is False and task['trigger_origin'] == 'UNVERIFIED'
now = datetime.now(timezone.utc)
entry.update(previous_entry_id=entry['entry_id'], entry_id='HANDOFF-20260911-BACKUP-OBSERVED',
    created_at_utc=now.isoformat(), created_at_hobart=now.astimezone(timezone(timedelta(hours=10))).isoformat(),
    result='RUNNING', scope='September11 observed 06:00 backup PASS and frozen receipt verification; trigger attribution remains UNVERIFIED',
    previous_day_backup=entry['backup_result'], backup_result=summary['backup'],
    task=summary['task'], task_origin_observation=task, guard=summary['guard'],
    selected_generation=summary['selected_generation'], last_verified_generation=summary['selected_generation'],
    current_phase='Unchanged receiver completed observed 06:00 run; A3 trigger attribution and remaining full acceptance evidence open',
    next_action='Close this evidence-only branch through the guarded PR CLI. Investigate a legitimate ordinary-user source of independent trigger attribution; do not infer it from a matching start time, enable privileged logging, replay a backup, or modify the accepted receiver just for closeout. Complete remaining A3 and A4 controls before physical work.',
    snapshot_notice='September11 task Ready/0, native scheduled PASS, guard PASS, three restore results PASS; Windows task history disabled. No new activation or manual start occurred in this inspection.',
    authorisation='Ongoing user authorization to finish recovery without Windows Yes/UAC; this slice performs read-only inspection and evidence closeout only.',
    reason='Record a real successful backup without inventing missing trigger provenance or physical recovery acceptance.')
entry['independent_states'].update(backup=summary['backup'], publication=publication,
    publication_v2=publication,
    current_day='September11 rolling payloads/index and live dashboard verified. Full natural ingest journal and dated-release acceptance remain separate; device symptom is unverified.')
entry['completed_gates'].extend([
    'PR671 merged b4a6e36a0f30c94bc1dbef64f51b863abbc3f302; merged audit20 clean and all substantive threads resolved',
    'September11 06:00:01 task execution completed06:10:16 nativePASS; guardPASS06:10:17; installed source/config unchanged',
    'Current catalog155 and component153/154/155 restore checksPASS; frozen metadata bindingPASS08:19:48',
    'All7 rollingv1 and2v2 payloads plus current dates-index verified08:18:56; browser and verify:local passed08:20'])
entry['open_gates'] = [g for g in entry['open_gates'] if not g.startswith('PR671')]
entry['open_gates'].insert(0, 'Independent trigger attribution unavailable because TaskScheduler Operational history disabled; no inference from06:00 alignment')
entry['timing'].update(natural_trigger_hobart='2026-09-12T06:00:00+10:00',
    observed_task_start_hobart=task['last_run'], observed_task_completed_at=summary['backup']['completed_at'],
    earliest_natural_terminal_inspection_hobart='Current September11 terminal inspected; future inspection after terminal only. Matching time does not close origin gap.')
entry['commands'].update(current_slice_workdir=str(ROOT),
    current_slice=['gh pr view --json number', 'npm run pr:merge -- --pr <number-returned-for-this-branch>', 'npm run pr:bot-feedback-audit'],
    manual_backup='NOT_RUN in this inspection; do not replay a successful backup',
    current_evidence={'summary':'docs/evidence/backup-observation-20260911/terminal-summary.json',
        'packet':summary['packet'], 'commands':summary['commands'], 'publication':publication['exact_command']})
entry['repository_state']['correction']={'path':str(ROOT), 'branch':'agent/backup-observation-0911',
    'base_sha':'b4a6e36a0f30c94bc1dbef64f51b863abbc3f302', 'clean_at_start':True, 'scope_of_changes':'Read-only observed backup/publication evidence only'}
entry['repository_state']['installed_receiver']['checked_at_hobart']='2026-09-11T06:10:17+10:00'
entry['repository_state']['installed_receiver']['current_cleanliness']='Exact source/config and805 private package files authenticated by successful guard; not replaced by this evidence branch'
entry['unresolved_findings'].append({'id':'September11-trigger-attribution', 'status':'UNVERIFIED',
    'issue':'06:00:01 start observed; disabled TaskScheduler Operational log supplies no independent trigger-origin event. Do not close A3 or advance A4 from timing alone.'})
entry['acceptance_criteria']['current_slice']='Preserve actual current native/guard/restore result and separately verify frozen receipts and public payloads; keep trigger attribution explicit; reviewed evidence PR only'
entry['revised_acceptance_criteria']=dict(entry['acceptance_criteria'])
existing={a['path'] for a in entry['evidence_artifacts']}
for p in sorted(E.rglob('*')):
    if p.is_file():
        relative=p.relative_to(ROOT).as_posix()
        assert relative not in existing
        raw=p.read_bytes()
        entry['evidence_artifacts'].append({'path':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
suffix=('\n\n## Entry `'+entry['entry_id']+'`\n\n```json\n'+json.dumps(entry,indent=2)+'\n```\n').encode()
path.write_bytes(old+suffix)
assert path.read_bytes().startswith(old)
print(json.dumps({'entry':entry['entry_id'],'evidence_files':len(entry['evidence_artifacts'])}))
