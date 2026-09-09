"""Append a complete recovery handoff without rewriting any previous bytes."""
import copy
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[3]
path = root / 'docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
original = path.read_bytes()
last = json.loads(re.findall(r'```json\s*\n(.*?)\n```', original.decode('utf-8'), re.S)[-1])
assert last['entry_id'] == 'HANDOFF-20260910-PRETRIGGER-READY'
v = copy.deepcopy(last)
now = datetime.now(timezone.utc)
v.update(entry_id='HANDOFF-20260910-PRIVATE-TOOLS-PREPARED', previous_entry_id=last['entry_id'],
         created_at_utc=now.isoformat(), created_at_hobart=now.astimezone(timezone(timedelta(hours=10))).isoformat(),
         result='RUNNING', current_phase='A3 repair after natural backup failure; private toolchain preparation',
         scope='Source, package and read-only runtime preparation; no task activation or backup started',
         reason='The 06:00 task failed on Git drift; Windows SSH also drifted and crashed during strict read-only probes.',
         next_action='Complete this source PR and applicable CI/review. Record D-023 with exact merged receiver, new immutable config and guard/package identities; verify predecessor lineage and ordinary-user task transaction, then run the user-authorized manual backup immediately. Do not wait for 06:00 or label it natural.',
         authorisation='User: Finish the previous work completely; never require a Windows Yes prompt; Do it now rather than 6am. This authorizes an ordinary-user repair and immediate controlled manual backup. It does not authorize relaxed host-key checks or fabricate natural/physical proof.',
         deviations=[], snapshot_notice='Installed task/config remain the September8 pair. New private-tool configs v1-v4 are rejected/staged proposals only. September9 backup evidence below remains dated history.')
v['independent_states'].update(
    capture='September10 natural marker and revision read with authenticated private SSH; full source/archive verification awaits the new backup.',
    finalization='Natural obs-2026-09-10-1fe80918fd39676f and revision obs-2026-09-10-d43214e888ca836b marker/ledger metadata observed. The selected backup pointer must be independently bound at execution.',
    publication='PASS at 08:26 Hobart: September10 rolling v1/v2, dated v1, date index and downloaded core hashes; no device acceptance implied.',
    publication_checked_at_utc='2026-09-09T22:26:32.127570+00:00',
    dashboard='Active/running at 08:56; /api/latest reports September10. No Pi deployment or restart performed.',
    backup='September10 06:00:01 task FAIL exit1 before route selection; no September10 backup data copied by this turn.',
    natural_trigger='FAIL: configured Git digest mismatch. Operational TaskScheduler event log disabled; no additional event-origin proof invented.',
    device_app='UNVERIFIED: displayed screen/date/error requested; ADB query failed with protocol error.',
    current_day='Public September10 rates and strict read-only runtime/service evidence verified; September10 backup not started.')
failure = json.loads((Path(__file__).parent / 'failure-state.json').read_bytes())
v['task'].update(last_run=failure['last_run'], last_task_result=failure['last_result'],
                 next_run=failure['next_run'], state=failure['state'],
                 status_checked_at_hobart=failure['at'],
                 latest_attempt_scope='September10 06:00:01 failure before backup; original stderr preserved.')
v['repository_state']['correction'].update(path=str(root), branch='agent/pinned-git-recovery-0910',
    base_sha='686eb709fd37fafe7a7c16c4403fa1e9a69af4b9', scope_of_changes='Private tool authentication, explicit Git SSH syntax, guarded receiver/tool transition and preserved evidence')
for key in ('production', 'installed_receiver'):
    v['repository_state'][key].update(checked_at_hobart='2026-09-10T08:56:34+10:00',
        current_cleanliness='PASS using private tools in read-only proposal; installed task configuration unchanged')
v['completed_gates'] += ['PR667 merged 686eb709fd37fafe7a7c16c4403fa1e9a69af4b9; prior workflow finding resolved',
    '140 focused tests passed including ordinary-token Windows child Git/exit behavior and transition lineage guards',
    'Proposed private tools authenticated; strict production/receiver read-only check PASS with exit0 and empty SSH stderr']
v['open_gates'] = ['Current private-tools source PR and exact merged candidate activation',
    'D-023 exact activation and immediate manual backup/restore evidence'] + last['open_gates'][1:]
v['timing'].update(earliest_documentation_start_hobart=v['created_at_hobart'],
    earliest_manual_start_hobart='Immediately after reviewed exact-candidate activation and fresh idle/ingest/predecessor checks, before 14:00 September10',
    latest_safe_stop_hobart='Manual backup must start before14:00; original six-hour task bound and22:00 cutoff remain; stop earlier on protected-workload conflict',
    natural_trigger_hobart='2026-09-11T06:00:00+10:00')
v['commands']['current_slice_workdir'] = str(root)
v['commands']['current_slice'] = ['npm run pr:merge -- --pr <resolved-private-tools-PR-number>', 'npm run pr:bot-feedback-audit']
v['commands']['activation'] = 'Prepare a create-new D-023 activation envelope with exact merged SHA/config/tool-contract/deployment hashes. Use laptop_backup_user_update.py with --tool-contract and --tool-contract-sha256, then Invoke-UserBackupTaskUpdate. Do not run against unresolved placeholders.'
v['commands']['manual_backup'] = 'After exact activation and original preflight gates, create manual-start evidence before Start-ScheduledTask -TaskName "AR-local user-session backup"; observe actual terminal receipts without competing triggers.'
v['known_risks'] += ['System Git and SSH updates invalidate installed hashes; private packages need deliberate future updates.',
    'Native Windows OpenSSH copies, including the staged preview client, failed strict process-exit validation and are not selected.',
    'The selected Git SSH needs explicit /dev/null syntax; no old receiver is compatible until the reviewed update is activated.']
v['compensating_controls'] += ['Every private package file, including DLLs, is verified; process-only PATH selects authenticated Git.',
    'Tool-enabled receiver transition still authenticates the existing full receipt lineage and pins production/operator/targets/SSH identity and host-key fields.',
    'All failed packages/configurations preserved; no blanket acceptance of SSH crash exits.']
v['acceptance_criteria']['current_slice'] = 'Applicable exact-head CI/review, whole-package and strict runtime proof, exact immutable activation intent before any task change, action-only update with XML/readback/rollback evidence, then manual backup and restore.'
v['revised_acceptance_criteria'] = copy.deepcopy(v['acceptance_criteria'])
v['rollback_or_preservation']['current_slice'] = 'No runtime mutation yet. Preserve all staged alternatives and old task/config. Future failed task action update restores the original exported action through the existing transaction.'
v['unresolved_findings'] = [x for x in last['unresolved_findings'] if x['id'] != 'PR666-3964098598'] + [
    {'id': 'natural-backup-20260910-tool-drift', 'status': 'RUNNING', 'issue': 'Private replacement prepared; source review and actual activation/manual backup remain.'}]
v['evidence_artifacts'] += [
    {'path': p.relative_to(root).as_posix(), 'bytes': p.stat().st_size,
     'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    for p in sorted(Path(__file__).parent.iterdir()) if p.is_file()]
with path.open('ab') as output:
    output.write(('\n\n## Entry `' + v['entry_id'] + '`\n\n```json\n' +
                  json.dumps(v, indent=2, ensure_ascii=False) + '\n```\n').encode('utf-8'))
assert path.read_bytes().startswith(original)
print(json.dumps({'entry_id': v['entry_id'], 'evidence_artifacts': len(v['evidence_artifacts']),
                  'previous_bytes_preserved': len(original)}))
