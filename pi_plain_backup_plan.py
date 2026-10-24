"""Pure source plan for a root-created, one-shot retained host queue service.

This module never installs or starts anything. Installation, root packet binding,
actual namespace proof and exact-head source review remain operator actions.
"""
import hashlib
import json
import re

ROOT='/usr/local/lib/ar-local-plain-backup'
QUEUE='/usr/local/lib/shared-pi-queue/pi_shared_queue.py'


def queue_argv(nonce,*,runtime=21600,wait=7200):
    if not re.fullmatch('[0-9a-f]{32}',nonce) or not 1<=runtime<=21600 or not 0<=wait<=86400:
        raise ValueError('fixed nonce and bounded queue runtime required')
    return ['/usr/bin/python3','-B',QUEUE,'run','--project','ar-local',
        '--resource','ar-local','--resource','host','--mode','exclusive','--cpu-slots','1',
        '--max-runtime',str(runtime),'--wait-timeout',str(wait),'--',
        '/usr/bin/python3','-I','-B',ROOT+'/parent.py',nonce]


def service_plan(nonce,*,mode="RUN_ARCHIVE",wait=None):
    if mode not in ("PROBE","RUN_ARCHIVE"):raise ValueError("fixed operation mode required")
    runtime=120 if mode=="PROBE" else 21600
    wait=(30 if mode=="PROBE" else 7200) if wait is None else wait
    argv=queue_argv(nonce,runtime=runtime,wait=wait)
    return {'unit':'ar-local-plain-backup-'+nonce+'.service','argv':argv,
        'queue_argv_sha256':hashlib.sha256(json.dumps(argv,separators=(',',':')).encode()).hexdigest(),
        'properties':{'User':'pi','Group':'pi','Type':'notify','NotifyAccess':'main',
            'CPUQuota':'100%','IOWeight':'10','TasksMax':'64','RuntimeMaxSec':str(runtime),
            'TimeoutStartSec':str(wait+60),'TimeoutStopSec':'45','KillMode':'control-group',
            'SendSIGKILL':'yes','NoNewPrivileges':'no','UMask':'0077',
            'ExecStopPost':'+/usr/bin/python3 -I -B '+ROOT+'/broker.py recover '+nonce},
        'sudoers_exact_commands':['/usr/bin/python3 -I -B '+ROOT+'/broker.py '+action+' '+nonce
            for action in ('acquire','finish','recover')]}
