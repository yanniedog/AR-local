"""Installed as broker.py; fixed root verbs only, never producer imports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

ROOT=Path("/usr/local/lib/ar-local-plain-backup")
STATE=Path("/var/lib/ar-local-plain-backup-control")


def bootstrap():
    if sys.platform!="linux" or os.geteuid()!=0 or Path(__file__).resolve()!=ROOT/"broker.py":
        raise RuntimeError("fixed installed Linux root broker required")
    for path in (ROOT,*ROOT.parents,STATE,*STATE.parents):
        info=path.lstat()
        if info.st_uid!=0 or stat.S_ISLNK(info.st_mode) or info.st_mode&0o022:
            raise RuntimeError("root control path is not protected")
    manifest=ROOT/"root-control-manifest.json"
    info=manifest.lstat()
    if info.st_uid!=0 or info.st_mode&0o022 or not stat.S_ISREG(info.st_mode) or info.st_size>65536:
        raise RuntimeError("root control manifest unavailable")
    value=json.loads(manifest.read_bytes())
    names={"broker.py","pi_plain_backup_core.py","pi_plain_backup_linux.py","pi_shared_queue_post_hooks.py",
           "pi_plain_drive_resources.py","parent.py","reconcile.py"}
    if set(value)!=names: raise RuntimeError("root import closure differs")
    for name,expected in value.items():
        path=ROOT/name; info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_nlink!=1
                or hashlib.sha256(path.read_bytes()).hexdigest()!=expected):
            raise RuntimeError("root import closure hash differs")
    sys.path.insert(0,str(ROOT))


def main(action,nonce):
    if action not in ("acquire","finish","recover") or not re.fullmatch("[0-9a-f]{32}",nonce):
        raise RuntimeError("fixed verb and nonce required")
    bootstrap()
    import fcntl
    import pi_plain_backup_core as broker_core
    from pi_plain_backup_linux import Host
    private=STATE/nonce
    info=private.lstat()
    if info.st_uid!=0 or not stat.S_ISDIR(info.st_mode) or info.st_mode&0o077:
        raise RuntimeError("protected nonce state required")
    fd=os.open(private/"lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        host=Host(nonce)
        if action=="acquire":
            result=broker_core.acquire(host,nonce)
            host.run_worker(host.packet(nonce),host.intent(nonce)["identity"])
            result["worker_result"]="PASS"
        else:
            result=broker_core.finish(host,nonce,recovery=action=="recover")
        print(json.dumps(result,sort_keys=True))
        return 0
    finally: os.close(fd)


if __name__=="__main__":
    try:
        if len(sys.argv)!=3: raise RuntimeError("fixed verb/nonce required")
        raise SystemExit(main(*sys.argv[1:]))
    except Exception as error:
        # Never include secret config, environment, argv or provider bodies.
        print(json.dumps({"result":"BLOCKED","error":type(error).__name__}))
        raise SystemExit(2)
