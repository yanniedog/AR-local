"""One ordinary-user control API call followed by unchanged scheduled verification."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OLD = Path(r'C:\code\backups\AR-local-user-session\private-tools-20260910-v5')
DEPLOYMENT_SHA = '9751b0441d9eec953b19de5f148018afdd76b99effcb8c60bb8449a79e63e314'
CONFIG_SHA = 'b5226e34e367393f9087b92c63dc6f6bd92054d7df2b24c88c45a793e529a9ff'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(OLD / 'private-tools-deployment.json') == DEPLOYMENT_SHA
deployment = json.loads((OLD / 'private-tools-deployment.json').read_bytes())
source = OLD / 'source'
assert sha(source / 'laptop_backup_git_dependency.py') == deployment['verifier_sha256']
sys.path.insert(0, str(source))
import laptop_backup_git_dependency as dependency
proof = dependency.verify_current(OLD / 'user-session-backup.json', CONFIG_SHA,
    Path(deployment['archive']), deployment['package_sha256'], Path(deployment['package_root']),
    Path(deployment['ssh_archive']), deployment['ssh_sha256'], Path(deployment['ssh_root']))
config = json.loads((OLD / 'user-session-backup.json').read_bytes())
os.environ['PATH'] = str(Path(config['git_path']).parent) + os.pathsep + os.environ['PATH']
os.environ['AR_USER_BACKUP_CONFIG_SHA256'] = CONFIG_SHA
import laptop_backup_user_session as user
import laptop_backup_scheduled as scheduled
import laptop_pull_backup as receiver
config = user.load_config(OLD / 'user-session-backup.json', CONFIG_SHA)
user.verify_release(config)
now = datetime.now(timezone.utc)
assert now.astimezone(user.HOBART).date().isoformat() == '2026-09-10' and user.allowed_start(now)
user.legacy_idle(config['legacy_task'])
assert config['lan_fallback_ipv4'] == '192.168.20.19'
transport = user.transport_contract()
arguments = user.scheduled_arguments(config, 'check', transport, config['lan_fallback_ipv4'])
args = scheduled.parser().parse_args(arguments)
allowed, reason = scheduled.open_transition_allows_invocation(args)
assert allowed, reason
intent = json.loads((OLD / 'D-023-activation-intent.json').read_bytes())
intent.update(id='D-025-CONTROL-API-REFRESH-20260910', result='INTENT',
    created_at_utc=now.isoformat(), created_at_hobart=now.astimezone(user.HOBART).isoformat(),
    reason='All v5 component restores passed but aggregate control freshness failed after a monitor clock tick. Refresh only control using the unchanged receiver API, then run the unchanged scheduled check to establish a real successful predecessor.',
    exact_commands={'operator':[sys.executable,*sys.argv], 'scheduled_check_arguments':arguments},
    wrapper_sha256=sha(Path(__file__)), deployment_proof=proof,
    deviations=[{'change':'Operator invokes the existing control backup API only',
      'controls':'No function replacement, timestamp normalization, timeout change or relaxed check. Fresh original preflight must show only control stale; same locks and strict transport; original scheduled check must report all components current.',
      'risk':'Stale observation or macro accidentally retained'}],
    acceptance=['Fresh original preflight accepts exact source/runtime and shows only control stale',
                'Control archive passes original restore checks',
                'Unchanged scheduled.main check passes with all components current'],
    rollback='Preserve all prior archives/receipts and any new failed result; no task or source change. No blind retry.')
with (ROOT / 'intent.json').open('x',encoding='utf-8') as stream:json.dump(intent,stream,indent=2)
outcome = {'result':'FAIL','decision':intent['id'],'intent_sha256':sha(ROOT / 'intent.json')}
try:
    with receiver.ReceiverLock(Path(config['target']) / 'user-session-lock'):
        code, stdout, stderr = scheduled.invoke_receiver(args, 'preflight')
        assert code == 0, stderr
        listing = json.loads(stdout)
        target = Path(config['target'])
        status = scheduled.scheduled_status(target, listing, args)
        outcome['before'] = status
        assert all(status[k]['status'] == 'UP_TO_DATE' for k in ('observation','macro','inventory'))
        assert not status['backfill_required'] and status['control']['status'] == 'STALE'
        scheduled.prepare_execution_lineage(target, args)
        child = receiver.parser().parse_args(scheduled.receiver_arguments(args,'backup-latest'))
        child.target = receiver.canonical_target(child.target)
        child.plan_raw_sha256 = receiver.verify_plan_document()['plan_raw_sha256']
        remote, helper_sha = receiver.install_remote_helper(child)
        try:
            with receiver.ReceiverLock(target):
                outcome['control'] = receiver.backup_one(child,remote,helper_sha,'control')
        finally:
            receiver.remove_remote_helper(child, remote)
        outcome['verification_exit_code'] = scheduled.main(arguments)
        outcome['result'] = 'PASS' if outcome['verification_exit_code'] == 0 else 'FAIL'
except BaseException as error:
    outcome['error'] = type(error).__name__ + ': ' + str(error)
    raise
finally:
    outcome.update(completed_at_utc=datetime.now(timezone.utc).isoformat(),natural_trigger=False,
                   physical_recovery='BLOCKED')
    with (ROOT / 'terminal.json').open('x',encoding='utf-8') as stream:json.dump(outcome,stream,indent=2)
    print(json.dumps(outcome))
raise SystemExit(0 if outcome['result'] == 'PASS' else 1)
