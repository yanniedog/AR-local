"""Append the complete observed D026 running state without altering older entries."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
E = Path(__file__).parent
path = ROOT / 'docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
old = path.read_bytes()
entry = json.loads(re.findall(rb'```json\s*(.*?)\s*```',old,re.S)[-1])
assert entry['entry_id'] == 'HANDOFF-20260910-PRIVATE-TOOLS-ACTIVATED'
decision = json.loads((E / 'D-026-activation-intent.json').read_bytes())
config = json.loads((E / 'user-session-backup.json').read_bytes())
task = json.loads((E / 'running-task.json').read_bytes())
prior = json.loads((E / 'D025/terminal.json').read_bytes())
publication = json.loads((E / 'publication/v2-publication-check.json').read_bytes())
now = datetime.now(timezone.utc)
entry.update(previous_entry_id=entry['entry_id'],entry_id='HANDOFF-20260910-RECOVERY-CLOCK-RUNNING',
    created_at_utc=now.isoformat(),created_at_hobart=now.astimezone(timezone(timedelta(hours=10))).isoformat(),
    result='RUNNING',scope='D024 rejection, real D025 successful predecessor, D026 exact activation and active manual verification',
    candidate_code_sha=config['candidate_sha'],receiver_path=config['receiver'],
    receiver_config_sha256=decision['config']['sha256'],plan_raw_sha256=decision['plan_raw_sha256'],
    current_phase='D026 corrected receiver installed; manual backup verification running',
    previous_runtime_execution=entry['backup_result'],previous_manual_recovery=prior,
    backup_result={'result':'RUNNING','origin':'manual','receiver_sha':config['candidate_sha'],
                   'started_at_hobart':task['last_run'],'natural_trigger':False},
    task=dict(task,name=task['task'],principal_triggers_settings_preserved=True),
    last_verified_generation=entry['selected_generation'],selected_generation=None,
    deviations=decision['deviations'],
    deviation_decision={'id':decision['id'],'path':'docs/evidence/recovery-clock-20260910/D-026-activation-intent.json',
                        'sha256':hashlib.sha256((E / 'D-026-activation-intent.json').read_bytes()).hexdigest(),
                        'created_before_activation':True},
    next_action='Observe the already running v7 task. Do not trigger another backup or acquire live reader locks. After terminal completion, freeze evidence, verify current receipts, append the complete actual terminal handoff and close the evidence PR. Preserve this pair for natural-trigger proof.',
    reason='Timestamp-only monitor changes produced a false stale control result; all recovery facts and raw bytes now remain verified while checked_at is excluded only from freshness identity.',
    snapshot_notice='v7 is installed and running. v6 was rejected before task mutation. v5 aggregate failure and D025 successful native check are separate immutable historical outcomes.')
entry['independent_states'].update(backup=entry['backup_result'],
    publication='September10 v1/core/date-index evidence plus complete v2 downloads PASS09:48:32; old v2 manifest-only check was limited evidence.',
    publication_v2=publication,
    current_day='Today public feeds verified; active v7 manual backup is not yet terminal. Device symptom remains unverified.')
entry['completed_gates'].extend([
    'PR669 runtime correction merged28f64e17; its Linux test-size failure fixed by PR670 with both full Linux and Windows CI PASS',
    'PR670 merged b6c5a4d8984ad2d2509514418c753cd555b0144f;60 focused size/regression checks PASS',
    'D025 original control API and unchanged scheduled check PASS09:55:33; successful predecessor3b76be3477997900aaeeefb253e1a76323c0f3d18214cbfa891d4062223581b7',
    'D026 exact ordinary-user task transaction PASS09:57:19 and probe PASS09:58:05; manual run started09:58:56',
    'Every v2 descriptor downloaded and size/hash/compression/date verified09:48:32'])
entry['open_gates'] = [x for x in entry['open_gates'] if not x.startswith(('Manual backup failed','Independent current receipt'))]
entry['open_gates'].insert(0,'D026 active manual task terminal, independent receipt binding and evidence PR closeout')
entry['timing'].update(manual_start_hobart=task['last_run'],
    earliest_natural_terminal_inspection_hobart='After September11 06:00 natural task is terminal; never inspect a manual run as natural proof')
entry['commands'].update(current_slice_workdir=str(ROOT),
    current_slice=['npm run pr:merge -- --pr <resolved-evidence-PR-number>','npm run pr:bot-feedback-audit'],
    activation=decision['exact_commands'],manual_backup='Already started once under D026; do not replay',
    current_evidence={'running_task':'docs/evidence/recovery-clock-20260910/running-task.json',
                      'terminal_rule':'Capture only after the active task is terminal; keep running snapshots dated.'})
entry['repository_state']['correction']={'path':str(ROOT),'branch':'agent/recovery-clock-activation-0910',
    'base_sha':config['candidate_sha'],'clean_at_start':True,'scope_of_changes':'Observed activation, predecessor recovery and complete v2 verification evidence only'}
entry['repository_state']['installed_receiver']={'path':config['receiver'],'sha':config['candidate_sha'],
    'clean_at_snapshot':True,'checked_at_hobart':'2026-09-10T09:58:05+10:00',
    'current_cleanliness':'805 package files and exact clean-source/config verification passed before guarded execution'}
entry['rollback_or_preservation']['current_slice']='v6 attempt rejected before mutation; v7 installation passed. Preserve both attempts and the v5 and D025 outcomes. Never downgrade merely to erase a failed result.'
entry['unresolved_findings']=[x for x in entry['unresolved_findings'] if x['id']!='manual-backup-20260910']
entry['unresolved_findings'].append({'id':'D026-current-backup','status':'RUNNING','issue':'Actual corrected-receiver manual result and independent receipt binding pending; do not infer from the probe or prior D025 PASS.'})
for artifact in sorted(E.rglob('*')):
    if artifact.is_file():
        raw=artifact.read_bytes()
        entry['evidence_artifacts'].append({'path':artifact.relative_to(ROOT).as_posix(),
            'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
suffix=('\n\n## Entry `'+entry['entry_id']+'`\n\n```json\n'+json.dumps(entry,indent=2)+'\n```\n').encode()
path.write_bytes(old+suffix)
assert path.read_bytes().startswith(old)
print(json.dumps({'entry':entry['entry_id'],'evidence_files':len(entry['evidence_artifacts'])}))
